from __future__ import annotations

import asyncio
import hashlib
import io
import json
import mimetypes
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .database import get_db
from .models import (
    Angle,
    Asset,
    Citation,
    Project,
    ProjectEvent,
    ProjectStatus,
    Scene,
    Source,
    SourceBlock,
)
from .schemas import (
    AngleSelection,
    ApprovalRequest,
    CitationRead,
    ExportItem,
    ExportList,
    JobRead,
    ProjectCreate,
    ProjectRead,
    RegenerateRequest,
    SceneRead,
    StoryboardRead,
    StoryboardUpdate,
)
from .services.citations import verify_storyboard
from .services.ingestion import (
    IngestionError,
    add_primary_source,
    add_supplement_source,
    purge_project_files_and_fts,
)
from .services.jobs import emit_event, enqueue_job
from .services.providers import make_providers
from .services.workflow import estimate_project_cost, project_blocks, project_speech_voice

router = APIRouter()


def _get_project(db: Session, project_id: str) -> Project:
    project = db.scalar(
        select(Project)
        .options(selectinload(Project.sources), selectinload(Project.angles))
        .where(Project.id == project_id)
    )
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在。")
    return project


def _scene_read(scene: Scene, db: Session) -> SceneRead:
    citations: list[CitationRead] = []
    for citation in scene.citations:
        block = db.get(SourceBlock, citation.block_id)
        source = db.get(Source, block.source_id) if block else None
        citations.append(
            CitationRead(
                id=citation.id,
                block_id=citation.block_id,
                claim_type=citation.claim_type,
                quote=citation.quote,
                verified=citation.verified,
                confidence=citation.confidence,
                locator=block.locator if block else None,
                source_title=source.title if source else None,
            )
        )
    return SceneRead(
        id=scene.id,
        ordinal=scene.ordinal,
        title=scene.title,
        narration=scene.narration,
        on_screen_text=scene.on_screen_text,
        visual_type=scene.visual_type,
        visual_prompt=scene.visual_prompt,
        duration_seconds=scene.duration_seconds,
        verified=scene.verified,
        revision=scene.revision,
        citations=citations,
        assets=[
            {
                "id": asset.id,
                "kind": asset.kind,
                "stale": asset.stale,
                "duration_seconds": asset.duration_seconds,
                "url": f"/files/{scene.project_id}/media/{Path(asset.path).name}",
            }
            for asset in scene.assets
            if Path(asset.path).exists()
        ],
    )


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {"status": "ok", "provider": settings.resolved_provider, "version": "0.1.0"}


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(title=payload.title.strip(), description=payload.description.strip())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .options(selectinload(Project.sources), selectinload(Project.angles))
            .order_by(Project.updated_at.desc())
        )
    )


@router.get("/projects/{project_id}", response_model=ProjectRead)
def read_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    return _get_project(db, project_id)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    _get_project(db, project_id)
    purge_project_files_and_fts(db, settings, project_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/sources", status_code=201)
async def add_source(
    project_id: str,
    kind: str = Form(...),
    title: str = Form(...),
    text_value: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = _get_project(db, project_id)
    try:
        if kind == "primary":
            if not file or not file.filename:
                raise IngestionError("主书必须上传 PDF 或 EPUB 文件。")
            payload = await file.read(settings.max_primary_bytes + 1)
            source = add_primary_source(db, settings, project, title, file.filename, payload)
        elif kind == "supplement":
            if file:
                raise IngestionError("补充资料请直接粘贴文本。")
            source = add_supplement_source(db, settings, project, title, text_value or "")
        else:
            raise IngestionError("来源类型必须是 primary 或 supplement。")
    except IngestionError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    emit_event(db, project.id, "source_added", f"已添加来源：《{source.title}》", 0.05)
    return {"id": source.id, "title": source.title, "char_count": source.char_count}


@router.post("/projects/{project_id}/music", status_code=201)
async def add_music(
    project_id: str,
    rights_attested: bool = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = _get_project(db, project_id)
    if not rights_attested:
        raise HTTPException(status_code=422, detail="必须确认拥有背景音乐使用权。")
    payload = await file.read(25 * 1024 * 1024 + 1)
    has_mp3_signature = payload.startswith(b"ID3") or (
        len(payload) >= 2 and payload[0] == 0xFF and payload[1] & 0xE0 == 0xE0
    )
    if (
        len(payload) > 25 * 1024 * 1024
        or not file.filename.lower().endswith(".mp3")
        or not has_mp3_signature
    ):
        raise HTTPException(status_code=422, detail="背景音乐必须是小于 25 MB 的 MP3。")
    path = settings.data_dir / "projects" / project.id / "media" / "background.mp3"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if probe.stdout.strip() not in {"mp3", "mp2"}:
            raise ValueError("not mp3")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="文件内容不是有效的 MP3 音频。") from exc
    for old in db.scalars(
        select(Asset).where(Asset.project_id == project.id, Asset.kind == "music")
    ):
        old.stale = True
    asset = Asset(
        project_id=project.id,
        kind="music",
        path=str(path),
        mime_type="audio/mpeg",
        checksum=hashlib.sha256(payload).hexdigest(),
        metadata_json={"rights_attested": True},
    )
    db.add(asset)
    db.commit()
    return {"id": asset.id, "filename": file.filename}


@router.post("/projects/{project_id}/analyze", response_model=JobRead, status_code=202)
def analyze(project_id: str, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    if not any(source.kind == "primary" for source in project.sources):
        raise HTTPException(status_code=409, detail="请先上传主书。")
    project.status = ProjectStatus.analyzing
    db.commit()
    return enqueue_job(
        db, project.id, "analyze", {"source_checksums": [s.checksum for s in project.sources]}
    )


@router.put("/projects/{project_id}/angle", response_model=JobRead, status_code=202)
def select_angle(project_id: str, payload: AngleSelection, db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    angle = db.get(Angle, payload.angle_id)
    if not angle or angle.project_id != project.id:
        raise HTTPException(status_code=404, detail="解读角度不存在。")
    project.selected_angle_id = angle.id
    project.status = ProjectStatus.storyboard_review
    db.commit()
    return enqueue_job(
        db,
        project.id,
        "storyboard",
        {"angle_id": angle.id, "book_map_revision": project.updated_at.isoformat()},
    )


@router.get("/projects/{project_id}/storyboard", response_model=StoryboardRead)
def get_storyboard(
    project_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StoryboardRead:
    project = _get_project(db, project_id)
    scenes = list(
        db.scalars(
            select(Scene)
            .options(selectinload(Scene.citations), selectinload(Scene.assets))
            .where(Scene.project_id == project.id)
            .order_by(Scene.ordinal)
        )
    )
    return StoryboardRead(
        project_id=project.id,
        revision=project.storyboard_revision,
        target_platform=project.target_platform,
        style=project.style,
        speech_voice=project_speech_voice(project, settings),
        estimated_cost_usd=project.estimated_cost_usd,
        scenes=[_scene_read(scene, db) for scene in scenes],
    )


@router.put("/projects/{project_id}/storyboard", response_model=StoryboardRead)
def update_storyboard(
    project_id: str,
    payload: StoryboardUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StoryboardRead:
    project = _get_project(db, project_id)
    if payload.revision != project.storyboard_revision:
        raise HTTPException(status_code=409, detail="故事板已经更新，请刷新后再编辑。")
    existing = {
        scene.id: scene
        for scene in db.scalars(
            select(Scene)
            .options(selectinload(Scene.citations), selectinload(Scene.assets))
            .where(Scene.project_id == project.id)
        )
    }
    retained: set[str] = set()
    valid_blocks = {
        item
        for item in db.scalars(select(SourceBlock.id).where(SourceBlock.project_id == project.id))
    }
    for ordinal, draft in enumerate(payload.scenes):
        scene = existing.get(draft.id or "")
        if not scene:
            scene = Scene(
                project_id=project.id, ordinal=ordinal, title=draft.title, narration=draft.narration
            )
            db.add(scene)
            db.flush()
        retained.add(scene.id)
        narration_changed = scene.narration != draft.narration
        visual_changed = (
            scene.visual_prompt != draft.visual_prompt or scene.visual_type != draft.visual_type
        )
        existing_citations = {
            (citation.block_id, citation.claim_type, citation.quote) for citation in scene.citations
        }
        requested_citations = {
            (citation.block_id, citation.claim_type, citation.quote) for citation in draft.citations
        }
        citations_changed = existing_citations != requested_citations
        scene.ordinal = ordinal
        scene.title = draft.title
        scene.narration = draft.narration
        scene.on_screen_text = draft.on_screen_text
        scene.visual_type = draft.visual_type
        scene.visual_prompt = draft.visual_prompt
        scene.duration_seconds = draft.duration_seconds
        if narration_changed or visual_changed or citations_changed:
            scene.revision += 1
            scene.verified = False
            for citation in scene.citations:
                citation.verified = False
                citation.confidence = 0.0
        for asset in scene.assets:
            if narration_changed and asset.kind == "audio":
                asset.stale = True
            if visual_changed and asset.kind == "image":
                asset.stale = True
        if citations_changed:
            scene.citations.clear()
            db.flush()
            for citation in draft.citations:
                if citation.block_id not in valid_blocks:
                    raise HTTPException(status_code=422, detail=f"{draft.title} 包含无效来源片段。")
                scene.citations.append(
                    Citation(
                        scene_id=scene.id,
                        block_id=citation.block_id,
                        claim_type=citation.claim_type,
                        quote=citation.quote,
                    )
                )
    for scene_id, scene in existing.items():
        if scene_id not in retained:
            db.delete(scene)
    project.target_platform = payload.target_platform
    project.style = payload.style
    previous_voice = project_speech_voice(project, settings)
    if previous_voice != payload.speech_voice:
        for scene in existing.values():
            for asset in scene.assets:
                if asset.kind == "audio":
                    asset.stale = True
    book_map = dict(project.book_map or {})
    project_settings = dict(book_map.get("project_settings", {}))
    project_settings["speech_voice"] = payload.speech_voice
    book_map["project_settings"] = project_settings
    project.book_map = book_map
    project.storyboard_revision += 1
    project.status = ProjectStatus.storyboard_review
    db.commit()
    project.estimated_cost_usd = estimate_project_cost(db, project.id)
    db.commit()
    emit_event(db, project.id, "storyboard_saved", "故事板修改已保存", 0.7)
    db.expire_all()
    return get_storyboard(project.id, db, settings)


@router.post("/projects/{project_id}/scenes/{scene_id}/image", status_code=201)
async def replace_scene_image(
    project_id: str,
    scene_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = _get_project(db, project_id)
    scene = db.scalar(
        select(Scene)
        .options(selectinload(Scene.assets))
        .where(Scene.id == scene_id, Scene.project_id == project.id)
    )
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在。")
    payload = await file.read(15 * 1024 * 1024 + 1)
    if len(payload) > 15 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="图片不能超过 15 MB。")
    try:
        with Image.open(io.BytesIO(payload)) as candidate:
            candidate.verify()
        with Image.open(io.BytesIO(payload)) as candidate:
            if candidate.width * candidate.height > 40_000_000:
                raise HTTPException(status_code=422, detail="图片像素尺寸过大。")
            converted = candidate.convert("RGB")
            media_dir = settings.data_dir / "projects" / project.id / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            path = media_dir / f"scene-{scene.ordinal:02d}-upload-{uuid4()}.png"
            converted.save(path, "PNG", optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=422, detail="文件不是有效的 PNG、JPEG 或 WebP 图片。"
        ) from exc
    for asset in scene.assets:
        if asset.kind == "image":
            asset.stale = True
    asset = Asset(
        project_id=project.id,
        scene_id=scene.id,
        kind="image",
        path=str(path),
        mime_type="image/png",
        checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
        metadata_json={"uploaded": True, "original_filename": Path(file.filename or "image").name},
    )
    db.add(asset)
    scene.visual_type = "illustration"
    scene.revision += 1
    project.storyboard_revision += 1
    project.status = ProjectStatus.storyboard_review
    db.commit()
    emit_event(db, project.id, "image_replaced", f"已替换 {scene.title} 的图片", 0.72)
    return {"id": asset.id, "scene_id": scene.id, "status": "ready_for_review"}


@router.post("/projects/{project_id}/storyboard/approve", response_model=JobRead, status_code=202)
def approve_storyboard(
    project_id: str,
    payload: ApprovalRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    project = _get_project(db, project_id)
    errors = verify_storyboard(db, project.id)
    if errors:
        raise HTTPException(
            status_code=422, detail={"message": "来源核验未通过。", "errors": errors}
        )
    project.estimated_cost_usd = estimate_project_cost(db, project.id)
    if project.estimated_cost_usd > settings.project_budget_usd and not payload.override_budget:
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "预计费用超过项目默认预算。",
                "estimated_cost_usd": project.estimated_cost_usd,
                "budget_usd": settings.project_budget_usd,
            },
        )
    project.status = ProjectStatus.approved
    db.commit()
    return enqueue_job(
        db,
        project.id,
        "media_render",
        {
            "storyboard_revision": project.storyboard_revision,
            "override_budget": payload.override_budget,
        },
    )


@router.post("/projects/{project_id}/scenes/{scene_id}/regenerate")
def regenerate_scene(
    project_id: str,
    scene_id: str,
    payload: RegenerateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = _get_project(db, project_id)
    scene = db.scalar(
        select(Scene)
        .options(selectinload(Scene.citations), selectinload(Scene.assets))
        .where(Scene.id == scene_id, Scene.project_id == project.id)
    )
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在。")
    if payload.target == "verify":
        errors = verify_storyboard(db, project.id)
        return {"verified": scene.verified, "errors": [e for e in errors if scene.title in e]}
    if payload.target == "narration":
        text_provider, _, _ = make_providers(settings)
        blocks = project_blocks(db, project.id, 80)
        scene_payload = {
            "title": scene.title,
            "narration": scene.narration,
            "on_screen_text": scene.on_screen_text,
            "visual_type": scene.visual_type,
            "visual_prompt": scene.visual_prompt,
            "duration_seconds": scene.duration_seconds,
            "citations": [
                {"block_id": c.block_id, "claim_type": c.claim_type, "quote": c.quote}
                for c in scene.citations
            ],
        }
        result = text_provider.regenerate_scene(scene_payload, payload.instruction, blocks)
        scene.narration = result["narration"]
        scene.on_screen_text = result.get("on_screen_text", scene.on_screen_text)
        scene.verified = False
        for asset in scene.assets:
            if asset.kind == "audio":
                asset.stale = True
    elif payload.target == "visual":
        if payload.instruction:
            scene.visual_prompt = f"{scene.visual_prompt}\n补充要求：{payload.instruction}"
        for asset in scene.assets:
            if asset.kind == "image":
                asset.stale = True
    elif payload.target == "audio":
        for asset in scene.assets:
            if asset.kind == "audio":
                asset.stale = True
    scene.revision += 1
    project.storyboard_revision += 1
    project.status = ProjectStatus.storyboard_review
    db.commit()
    return {"scene_id": scene.id, "revision": scene.revision, "status": "ready_for_review"}


@router.get("/projects/{project_id}/events")
async def events(
    project_id: str,
    request: Request,
    after: int = 0,
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)

    async def stream():
        cursor = after
        while not await request.is_disconnected():
            rows = list(
                db.scalars(
                    select(ProjectEvent)
                    .where(ProjectEvent.project_id == project_id, ProjectEvent.id > cursor)
                    .order_by(ProjectEvent.id)
                )
            )
            for event in rows:
                cursor = event.id
                payload = {
                    "id": event.id,
                    "kind": event.kind,
                    "message": event.message,
                    "progress": event.progress,
                    "data": event.data,
                }
                yield f"id: {event.id}\nevent: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/projects/{project_id}/exports", response_model=ExportList)
def exports(
    project_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExportList:
    _get_project(db, project_id)
    export_dir = settings.data_dir / "projects" / project_id / "exports"
    items = []
    if export_dir.exists():
        for path in sorted(export_dir.iterdir()):
            if path.is_file():
                items.append(
                    ExportItem(
                        name=path.name,
                        size=path.stat().st_size,
                        url=f"/files/{project_id}/exports/{path.name}",
                    )
                )
    return ExportList(project_id=project_id, items=items)


@router.get("/files/{project_id}/{category}/{filename}")
def files(
    project_id: str,
    category: str,
    filename: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _get_project(db, project_id)
    if category not in {"exports", "media"} or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="文件不存在。")
    path = (settings.data_dir / "projects" / project_id / category / filename).resolve()
    project_root = (settings.data_dir / "projects" / project_id).resolve()
    if not path.is_relative_to(project_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在。")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0], filename=path.name)
