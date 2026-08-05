from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import (
    Angle,
    Asset,
    Citation,
    Job,
    JobStatus,
    Project,
    ProjectStatus,
    Scene,
    Source,
    SourceBlock,
)
from .citations import verify_storyboard
from .jobs import emit_event
from .providers import ImageProvider, SpeechProvider, TextProvider, probe_duration


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_blocks(db: Session, project_id: str, limit: int | None = None) -> list[dict]:
    statement = (
        select(SourceBlock, Source)
        .join(Source, Source.id == SourceBlock.source_id)
        .where(SourceBlock.project_id == project_id)
        .order_by(Source.kind.desc(), SourceBlock.ordinal)
    )
    if limit:
        statement = statement.limit(limit)
    return [
        {
            "id": block.id,
            "source_id": block.source_id,
            "source_title": source.title,
            "locator": block.locator,
            "text": block.text,
        }
        for block, source in db.execute(statement).all()
    ]


def analyze_project(db: Session, project: Project, text_provider: TextProvider) -> dict:
    blocks = project_blocks(db, project.id)
    if not blocks:
        raise ValueError("项目还没有可分析的来源片段。")
    if not any(source.kind == "primary" for source in project.sources):
        raise ValueError("请先上传主书。")
    project.status = ProjectStatus.analyzing
    db.commit()
    emit_event(db, project.id, "analysis", "正在建立可追溯的书籍地图", 0.15)
    project.book_map = text_provider.build_book_map(project.title, blocks)
    db.query(Angle).filter(Angle.project_id == project.id).delete()
    db.commit()
    emit_event(db, project.id, "analysis", "正在生成五个解读角度", 0.55)
    angles = text_provider.generate_angles(project.title, project.book_map, blocks)
    valid_block_ids = {block["id"] for block in blocks}
    for ordinal, angle in enumerate(angles[:5]):
        evidence = [item for item in angle.get("evidence_block_ids", []) if item in valid_block_ids]
        if not evidence:
            evidence = [blocks[ordinal % len(blocks)]["id"]]
        db.add(
            Angle(
                project_id=project.id,
                ordinal=ordinal,
                title=angle["title"],
                hook=angle["hook"],
                thesis=angle["thesis"],
                audience_value=angle["audience_value"],
                evidence_block_ids=evidence,
            )
        )
    project.status = ProjectStatus.angles_ready
    db.commit()
    emit_event(db, project.id, "analysis_complete", "五个解读角度已经准备好", 1.0)
    source_chars = sum(len(block["text"]) for block in blocks)
    return {
        "angle_count": 5,
        "source_chars": source_chars,
        "estimated_input_tokens": round(source_chars / 2.2),
    }


def build_storyboard(db: Session, project: Project, text_provider: TextProvider) -> dict:
    angle = db.get(Angle, project.selected_angle_id)
    if not angle or angle.project_id != project.id:
        raise ValueError("没有有效的已选解读角度。")
    blocks = project_blocks(db, project.id, 100)
    angle_payload = {
        "id": angle.id,
        "title": angle.title,
        "hook": angle.hook,
        "thesis": angle.thesis,
        "audience_value": angle.audience_value,
        "evidence_block_ids": angle.evidence_block_ids,
    }
    emit_event(db, project.id, "storyboard", "正在生成场景蓝图", 0.2)
    drafts = text_provider.generate_storyboard(project.title, angle_payload, project.style, blocks)
    valid_blocks = {block["id"]: block for block in blocks}
    db.query(Scene).filter(Scene.project_id == project.id).delete()
    db.flush()
    for ordinal, draft in enumerate(drafts[:18]):
        scene = Scene(
            project_id=project.id,
            ordinal=ordinal,
            title=draft["title"],
            narration=draft["narration"],
            on_screen_text=draft.get("on_screen_text", ""),
            visual_type=draft.get("visual_type", "text_card"),
            visual_prompt=draft.get("visual_prompt", ""),
            duration_seconds=max(3.0, min(45.0, float(draft.get("duration_seconds", 12)))),
            verified=False,
        )
        db.add(scene)
        db.flush()
        citations = draft.get("citations", [])
        for item in citations:
            block_id = item.get("block_id")
            if block_id not in valid_blocks:
                block_id = blocks[ordinal % len(blocks)]["id"]
            db.add(
                Citation(
                    scene_id=scene.id,
                    block_id=block_id,
                    claim_type=item.get("claim_type", "interpretation"),
                    quote=item.get("quote", "")[:500],
                )
            )
    project.storyboard_revision += 1
    project.status = ProjectStatus.storyboard_review
    db.commit()
    errors = verify_storyboard(db, project.id)
    project.estimated_cost_usd = estimate_project_cost(db, project.id)
    db.commit()
    emit_event(
        db,
        project.id,
        "storyboard_complete",
        "场景卡已经准备好，请审核内容与来源",
        1.0,
        {"verification_warnings": len(errors)},
    )
    return {
        "scene_count": len(drafts),
        "narration_chars": sum(len(item.get("narration", "")) for item in drafts),
        "verification_warnings": errors,
    }


def estimate_project_cost(db: Session, project_id: str) -> float:
    sources = list(db.scalars(select(Source).where(Source.project_id == project_id)))
    scenes = list(db.scalars(select(Scene).where(Scene.project_id == project_id)))
    source_chars = sum(item.char_count for item in sources)
    narration_chars = sum(len(item.narration) for item in scenes)
    image_count = min(12, sum(item.visual_type == "illustration" for item in scenes))
    input_tokens = source_chars / 2.2
    output_tokens = max(3000, narration_chars / 1.2)
    text_cost = input_tokens / 1_000_000 * 2.5 + output_tokens / 1_000_000 * 15
    image_cost = image_count * 0.10
    speech_cost = narration_chars / 1_000_000 * 30
    return round(text_cost + image_cost + speech_cost, 2)


def project_speech_voice(project: Project, settings: Settings) -> str:
    project_settings = (project.book_map or {}).get("project_settings", {})
    return project_settings.get("speech_voice", settings.speech_voice)


def _upsert_asset(
    db: Session,
    project_id: str,
    scene_id: str | None,
    kind: str,
    path: Path,
    mime_type: str,
    duration: float | None = None,
    metadata: dict | None = None,
) -> Asset:
    asset = db.scalar(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.scene_id == scene_id,
            Asset.kind == kind,
            Asset.stale.is_(False),
        )
    )
    if asset and Path(asset.path).exists():
        return asset
    asset = Asset(
        project_id=project_id,
        scene_id=scene_id,
        kind=kind,
        path=str(path),
        mime_type=mime_type,
        checksum=_hash_file(path),
        duration_seconds=duration,
        metadata_json=metadata or {},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def generate_media(
    db: Session,
    settings: Settings,
    project: Project,
    image_provider: ImageProvider,
    speech_provider: SpeechProvider,
) -> dict:
    scenes = list(
        db.scalars(
            select(Scene)
            .options(selectinload(Scene.assets))
            .where(Scene.project_id == project.id)
            .order_by(Scene.ordinal)
        )
    )
    if not scenes:
        raise ValueError("故事板没有场景。")
    project.status = ProjectStatus.generating_media
    db.commit()
    media_dir = settings.data_dir / "projects" / project.id / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    illustration_count = 0
    for index, scene in enumerate(scenes):
        audio_asset = next(
            (
                a
                for a in scene.assets
                if a.kind == "audio" and not a.stale and Path(a.path).exists()
            ),
            None,
        )
        if not audio_asset:
            suffix = ".mp3" if settings.resolved_provider == "openai" else ".wav"
            audio_path = media_dir / f"scene-{scene.ordinal:02d}-audio{suffix}"
            speech_provider.synthesize(
                scene.narration, audio_path, project_speech_voice(project, settings)
            )
            duration = probe_duration(audio_path)
            scene.duration_seconds = duration
            _upsert_asset(
                db,
                project.id,
                scene.id,
                "audio",
                audio_path,
                "audio/mpeg" if suffix == ".mp3" else "audio/wav",
                duration,
            )
        if scene.visual_type == "illustration" and illustration_count < settings.max_ai_images:
            illustration_count += 1
            image_asset = next(
                (
                    a
                    for a in scene.assets
                    if a.kind == "image" and not a.stale and Path(a.path).exists()
                ),
                None,
            )
            if not image_asset:
                image_path = media_dir / f"scene-{scene.ordinal:02d}-image.png"
                image_provider.generate(scene.visual_prompt, image_path, project.title)
                _upsert_asset(db, project.id, scene.id, "image", image_path, "image/png")
        db.commit()
        emit_event(
            db,
            project.id,
            "media",
            f"已生成场景 {index + 1}/{len(scenes)} 的媒体",
            (index + 1) / len(scenes) * 0.82,
        )
    return {
        "scene_count": len(scenes),
        "image_count": illustration_count,
        "speech_chars": sum(len(scene.narration) for scene in scenes),
        "estimated_cost_usd": project.estimated_cost_usd,
    }


def _format_locator(locator: dict) -> str:
    if locator.get("type") == "pdf":
        start = locator.get("page_start")
        end = locator.get("page_end", start)
        return f"第 {start} 页" if start == end else f"第 {start}–{end} 页"
    if locator.get("type") == "epub":
        return f"{locator.get('chapter', '章节')} · 段落 {locator.get('paragraph_start', 1)}"
    return f"{locator.get('section', '补充资料')} · 段落 {locator.get('paragraph_start', 1)}"


def _sentence_captions(narration: str, start_seconds: float, duration: float) -> list[dict]:
    sentences = [
        item.strip()
        for item in __import__("re").split(r"(?<=[。！？!?])", narration)
        if item.strip()
    ]
    if not sentences:
        sentences = [narration]
    weights = [max(1, len(item)) for item in sentences]
    total = sum(weights)
    cursor = start_seconds
    output: list[dict] = []
    for sentence, weight in zip(sentences, weights, strict=True):
        length = duration * weight / total
        output.append({"start": cursor, "end": cursor + length, "text": sentence})
        cursor += length
    return output


def prepare_render_input(db: Session, settings: Settings, project: Project) -> tuple[Path, Path]:
    scenes = list(
        db.scalars(
            select(Scene)
            .options(
                selectinload(Scene.assets),
                selectinload(Scene.citations).selectinload(Citation.block),
            )
            .where(Scene.project_id == project.id)
            .order_by(Scene.ordinal)
        )
    )
    project_dir = settings.data_dir / "projects" / project.id
    render_dir = project_dir / "render-input"
    public_dir = render_dir / "public"
    if render_dir.exists():
        shutil.rmtree(render_dir)
    public_dir.mkdir(parents=True)
    payload_scenes: list[dict] = []
    cursor = 0.0
    for scene in scenes:
        audio = next((a for a in scene.assets if a.kind == "audio" and not a.stale), None)
        image = next((a for a in scene.assets if a.kind == "image" and not a.stale), None)
        if not audio:
            raise ValueError(f"{scene.title} 缺少音频。")
        audio_name = f"audio/{scene.id}{Path(audio.path).suffix}"
        (public_dir / "audio").mkdir(exist_ok=True)
        shutil.copy2(audio.path, public_dir / audio_name)
        image_name: str | None = None
        if image:
            image_name = f"images/{scene.id}{Path(image.path).suffix}"
            (public_dir / "images").mkdir(exist_ok=True)
            shutil.copy2(image.path, public_dir / image_name)
        source_label = ""
        if scene.citations:
            citation = scene.citations[0]
            source = db.get(Source, citation.block.source_id)
            source_label = f"《{source.title}》{_format_locator(citation.block.locator)}"
        duration = audio.duration_seconds or scene.duration_seconds
        payload_scenes.append(
            {
                "id": scene.id,
                "title": scene.title,
                "narration": scene.narration,
                "onScreenText": scene.on_screen_text,
                "visualType": scene.visual_type,
                "imageSrc": image_name,
                "audioSrc": audio_name,
                "durationInFrames": max(90, round(duration * 30)),
                "sourceLabel": source_label,
                "captions": [
                    {**caption, "start": caption["start"] - cursor, "end": caption["end"] - cursor}
                    for caption in _sentence_captions(scene.narration, cursor, duration)
                ],
            }
        )
        cursor += duration
    music = db.scalar(
        select(Asset).where(
            Asset.project_id == project.id,
            Asset.scene_id.is_(None),
            Asset.kind == "music",
            Asset.stale.is_(False),
        )
    )
    music_name = None
    if music and Path(music.path).exists():
        music_name = f"music/{music.id}{Path(music.path).suffix}"
        (public_dir / "music").mkdir(exist_ok=True)
        shutil.copy2(music.path, public_dir / music_name)
    payload = {
        "title": project.title,
        "style": project.style,
        "scenes": payload_scenes,
        "musicSrc": music_name,
        "aiVoiceDisclosure": "本内容使用 AI 合成语音",
        "publicDir": str(public_dir.resolve()),
    }
    input_path = render_dir / "input.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return input_path, project_dir / "exports"


def render_and_export(
    db: Session, settings: Settings, project: Project, text_provider: TextProvider
) -> dict:
    project.status = ProjectStatus.rendering
    db.commit()
    emit_event(db, project.id, "render", "正在准备 Remotion 渲染", 0.85)
    input_path, export_dir = prepare_render_input(db, settings, project)
    export_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[4]
    subprocess.run(
        [
            shutil.which("npm") or "npm",
            "--workspace",
            "@content-agent/video",
            "run",
            "render",
            "--",
            "--input",
            str(input_path.resolve()),
            "--output",
            str(export_dir.resolve()),
        ],
        cwd=repo_root,
        check=True,
    )
    _write_exports(db, settings, project, export_dir, text_provider)
    project.status = ProjectStatus.completed
    db.commit()
    emit_event(db, project.id, "complete", "视频和发布包已经生成", 1.0)
    return {"export_dir": str(export_dir)}


def _write_exports(
    db: Session,
    settings: Settings,
    project: Project,
    export_dir: Path,
    text_provider: TextProvider,
) -> None:
    scenes = list(
        db.scalars(
            select(Scene)
            .options(
                selectinload(Scene.assets),
                selectinload(Scene.citations).selectinload(Citation.block),
            )
            .where(Scene.project_id == project.id)
            .order_by(Scene.ordinal)
        )
    )
    concat_path = export_dir / "audio-concat.txt"
    audio_paths = [
        next(a for a in scene.assets if a.kind == "audio" and not a.stale).path for scene in scenes
    ]
    concat_path.write_text(
        "\n".join(
            f"file '{Path(path).resolve().as_posix().replace(chr(39), "'\\''")}'"
            for path in audio_paths
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(export_dir / "narration.mp3"),
        ],
        check=True,
        capture_output=True,
    )
    concat_path.unlink(missing_ok=True)
    captions: list[dict] = []
    cursor = 0.0
    for scene in scenes:
        audio = next(a for a in scene.assets if a.kind == "audio" and not a.stale)
        duration = audio.duration_seconds or scene.duration_seconds
        captions.extend(_sentence_captions(scene.narration, cursor, duration))
        cursor += duration
    (export_dir / "captions.srt").write_text(_to_srt(captions), encoding="utf-8-sig")
    storyboard = {
        "project_id": project.id,
        "title": project.title,
        "revision": project.storyboard_revision,
        "scenes": [
            {
                "id": scene.id,
                "ordinal": scene.ordinal,
                "title": scene.title,
                "narration": scene.narration,
                "on_screen_text": scene.on_screen_text,
                "visual_type": scene.visual_type,
                "duration_seconds": scene.duration_seconds,
                "verified": scene.verified,
                "citations": [
                    {
                        "block_id": citation.block_id,
                        "claim_type": citation.claim_type,
                        "quote": citation.quote,
                        "verified": citation.verified,
                        "confidence": citation.confidence,
                        "locator": citation.block.locator,
                        "source_title": db.get(Source, citation.block.source_id).title,
                    }
                    for citation in scene.citations
                ],
            }
            for scene in scenes
        ],
    }
    (export_dir / "storyboard.json").write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sources_lines = [f"# 《{project.title}》来源清单", ""]
    seen: set[tuple[str, str]] = set()
    for scene in scenes:
        for citation in scene.citations:
            source = db.get(Source, citation.block.source_id)
            key = (source.id, json.dumps(citation.block.locator, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            sources_lines.append(f"- 《{source.title}》{_format_locator(citation.block.locator)}")
    (export_dir / "sources.md").write_text("\n".join(sources_lines) + "\n", encoding="utf-8")
    angle = db.get(Angle, project.selected_angle_id)
    (export_dir / "publishing-copy.md").write_text(
        text_provider.generate_publishing_copy(project.title, angle.title if angle else "文学解读"),
        encoding="utf-8",
    )
    manifest = {
        "project_id": project.id,
        "generated_at": datetime.now(UTC).isoformat(),
        "format": {"width": 1080, "height": 1920, "fps": 30, "video": "h264", "audio": "aac"},
        "ai_voice": True,
        "provider": settings.resolved_provider,
        "models": {
            "text": settings.text_model,
            "image": settings.image_model,
            "speech": settings.speech_model,
            "voice": project_speech_voice(project, settings),
        },
        "storyboard_revision": project.storyboard_revision,
        "estimated_cost_usd": project.estimated_cost_usd,
        "sources": [
            {
                "id": source.id,
                "title": source.title,
                "type": source.source_type,
                "checksum": source.checksum,
            }
            for source in db.scalars(select(Source).where(Source.project_id == project.id))
        ],
        "files": {},
    }
    for path in export_dir.iterdir():
        if path.is_file() and path.name != "manifest.json":
            manifest["files"][path.name] = {
                "bytes": path.stat().st_size,
                "sha256": _hash_file(path),
            }
    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _to_srt(captions: list[dict]) -> str:
    def stamp(seconds: float) -> str:
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        secs, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"

    return (
        "\n\n".join(
            f"{index}\n{stamp(item['start'])} --> {stamp(item['end'])}\n{item['text']}"
            for index, item in enumerate(captions, start=1)
        )
        + "\n"
    )


def process_job(
    db: Session,
    settings: Settings,
    job: Job,
    text_provider: TextProvider,
    image_provider: ImageProvider,
    speech_provider: SpeechProvider,
) -> None:
    project = db.scalar(
        select(Project)
        .options(selectinload(Project.sources), selectinload(Project.angles))
        .where(Project.id == job.project_id)
    )
    if not project:
        raise ValueError("项目已经不存在。")
    if job.job_type == "analyze":
        output = analyze_project(db, project, text_provider)
    elif job.job_type == "storyboard":
        output = build_storyboard(db, project, text_provider)
    elif job.job_type == "media_render":
        media = generate_media(db, settings, project, image_provider, speech_provider)
        rendered = render_and_export(db, settings, project, text_provider)
        output = {**media, **rendered}
    else:
        raise ValueError(f"未知任务类型：{job.job_type}")
    job.status = JobStatus.completed
    job.output = output
    job.finished_at = datetime.now(UTC)
    db.commit()


def fail_job(db: Session, job: Job, error: Exception) -> None:
    job.error = str(error)[:4000]
    if job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        emit_event(db, job.project_id, "retry", f"任务失败，准备重试：{error}")
    else:
        job.status = JobStatus.failed
        job.finished_at = datetime.now(UTC)
        project = db.get(Project, job.project_id)
        if project:
            project.status = ProjectStatus.failed
        emit_event(db, job.project_id, "failed", f"任务失败：{error}", 1.0)
    db.commit()
