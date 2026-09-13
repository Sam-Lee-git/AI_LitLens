"""Render the reviewed Crime and Punishment pilot using the app's media contracts.

Run from the repository root. Real, chargeable speech; no mock/silent fallback.
The editorial script and images are supplied by the agent, not claimed as an
unattended title-to-video acceptance test. Sentence audio is hash-cached.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "api"))

from bs4 import BeautifulSoup  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Angle, Citation, Project, ProjectStatus, Scene, Source, SourceBlock  # noqa: E402
from app.services.jobs import emit_event  # noqa: E402
from app.services.providers import MockTextProvider, OpenAISpeechProvider  # noqa: E402
from app.services.workflow import _hash_file, _to_srt, _upsert_asset, _write_exports, prepare_render_input  # noqa: E402

PILOT = ROOT / "data" / "pilots" / "crime-and-punishment"
SCRIPT = ROOT / "examples" / "crime-and-punishment-pilot.json"
RATE = 48000
FPS = 30
CHAPTERS = {
    "第一部第一章": "link2HCH0001", "第一部第七章": "link2HCH0007",
    "第二部第一章": "link2HCH0008", "第二部第二章": "link2HCH0009",
    "第二部第七章": "link2HCH0014", "第三部第一章": "link2HCH0015",
    "第三部第五章": "link2HCH0019", "第五部第四章": "link2HCH0030",
    "第六部第八章": "link2HCH0039", "尾声第一章": "link2H_EPIL",
    "尾声第二章": "link2H_EPIL",
}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def chapter_texts() -> dict[str, str]:
    soup = BeautifulSoup((PILOT / "reference.html").read_text(encoding="utf-8"), "html.parser")
    output = {}
    for label, anchor in CHAPTERS.items():
        heading = soup.find(id=anchor).parent
        paragraphs = []
        include = not label.startswith("尾声")
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) == "h2":
                break
            if getattr(sibling, "name", None) == "h3" and label.startswith("尾声"):
                include = sibling.get_text(strip=True) == ("II" if "第二" in label else "I")
            if include and getattr(sibling, "name", None) == "p":
                paragraphs.append(sibling.get_text(" ", strip=True))
        text = "\n\n".join(paragraphs)
        if len(text) < 1000:
            raise ValueError(f"Could not extract primary chapter: {label}")
        output[label] = text
    return output


def create_project(db, settings, script: dict) -> Project:
    state_path = PILOT / "state.json"
    script_hash = _hash_file(SCRIPT)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["script_sha256"] != script_hash:
            raise ValueError("Script changed. Keep this pilot intact; create a new pilot revision.")
        project = db.get(Project, state["project_id"])
        if project is None:
            raise ValueError("Pilot project was removed; stale state will not recreate it silently.")
        return project
    texts = chapter_texts()
    project = Project(title=script["title"], description=script["series"] + "；" + script["editorial_mode"],
                      style=script["style"], status=ProjectStatus.approved, storyboard_revision=1)
    db.add(project)
    db.flush()
    project_dir = settings.data_dir.resolve() / "projects" / project.id
    project_dir.mkdir(parents=True, exist_ok=True)
    reference_path = project_dir / "reference.html"
    shutil.copy2(PILOT / "reference.html", reference_path)
    source = Source(project_id=project.id, kind="primary", source_type="reference_html",
                    title="罪与罚", checksum=_hash_file(reference_path), stored_path=str(reference_path),
                    char_count=sum(len(t) for t in texts.values()))
    db.add(source)
    db.flush()
    blocks = {}
    for index, (label, text) in enumerate(texts.items()):
        block = SourceBlock(project_id=project.id, source_id=source.id, ordinal=index,
                            locator={"type": "reference_html", "section": label,
                                     "url": script["source_url"] + "#" + CHAPTERS[label],
                                     "edition": script["source_edition"]},
                            text=text, checksum=hashlib.sha256(text.encode()).hexdigest())
        db.add(block)
        db.flush()
        blocks[label] = block
    angle = Angle(project_id=project.id, ordinal=0, title="谁给了你伤害别人的权利？",
                  hook=script["scenes"][0]["lines"][0], thesis=script["thesis"],
                  audience_value="先了解故事框架，再讨论理想、自我证明与责任。",
                  evidence_block_ids=[b.id for b in blocks.values()])
    db.add(angle)
    db.flush()
    project.selected_angle_id = angle.id
    project.book_map = {"editorial_mode": script["editorial_mode"], "pilot_script_hash": script_hash}
    for index, item in enumerate(script["scenes"]):
        scene = Scene(project_id=project.id, ordinal=index, title=item["title"],
                      narration="".join(item["lines"]), on_screen_text=item["screen"],
                      visual_type="illustration" if item["image"] else "text_card", verified=True)
        db.add(scene)
        db.flush()
        for label in item["references"]:
            db.add(Citation(scene_id=scene.id, block_id=blocks[label].id,
                           claim_type=item["claim_type"], quote="", verified=True,
                           confidence=0.9))
    # This pilot is agent-reviewed. This flag is not a semantic auto-verifier.
    db.commit()
    write_json(state_path, {"project_id": project.id, "script_sha256": script_hash})
    emit_event(db, project.id, "pilot", "试播讲稿已由 Agent 核对原著，开始真实配音", 0.1)
    return project


def synthesize_line(settings, line: str) -> tuple[Path, bool]:
    identity = json.dumps([settings.speech_model, settings.speech_voice, line], ensure_ascii=False)
    cache = PILOT / "speech-cache" / (hashlib.sha256(identity.encode()).hexdigest() + ".wav")
    if cache.exists():
        with wave.open(str(cache)) as audio:
            if audio.getnframes() > RATE // 2:
                return cache, True
    mp3 = cache.with_suffix(".mp3")
    if not mp3.exists():
        # SDK retries transient errors at most twice. Do not wrap another retry loop.
        OpenAISpeechProvider(settings).synthesize(line, mp3)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(RATE),
                    "-c:a", "pcm_s16le", str(cache)], check=True, capture_output=True)
    return cache, False


def media(db, settings, project: Project, script: dict) -> None:
    lines = list(dict.fromkeys(line for item in script["scenes"] for line in item["lines"]))
    chars = sum(map(len, lines))
    # Conservative local speech allowance, not an account billing report.
    if chars > 2000 or chars * 0.001 > settings.project_budget_usd:
        raise ValueError("Pilot speech allowance exceeds budget; no call made.")
    project.status = ProjectStatus.generating_media
    db.commit()
    cache = {}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(synthesize_line, settings, line): line for line in lines}
        for future in as_completed(futures):
            path, reused = future.result()
            cache[futures[future]] = path
            print(f"Speech {len(cache)}/{len(lines)} {'cached' if reused else 'generated'}", flush=True)
    project_dir = settings.data_dir.resolve() / "projects" / project.id
    media_dir = project_dir / "media"
    media_dir.mkdir(exist_ok=True)
    scenes = list(db.scalars(select(Scene).where(Scene.project_id == project.id).order_by(Scene.ordinal)))
    timings = []
    for scene, item in zip(scenes, script["scenes"], strict=True):
        pcm = bytearray()
        captions = []
        for line in item["lines"]:
            start = len(pcm) / (RATE * 2)
            with wave.open(str(cache[line])) as audio:
                assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, RATE)
                pcm.extend(audio.readframes(audio.getnframes()))
            pcm.extend(bytes(round(RATE * 0.12) * 2))
            captions.append({"start": start, "end": len(pcm) / (RATE * 2), "text": line})
        frames = math.ceil(len(pcm) / 2 / (RATE / FPS))
        pcm.extend(bytes(frames * (RATE // FPS) * 2 - len(pcm)))
        captions[-1]["end"] = frames / FPS
        output = media_dir / f"scene-{scene.ordinal:02d}-audio.wav"
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(RATE)
            audio.writeframes(pcm)
        scene.duration_seconds = frames / FPS
        _upsert_asset(db, project.id, scene.id, "audio", output, "audio/wav", frames / FPS,
                      {"captions": captions, "alignment": "individually synthesized sentences"})
        if item["image"]:
            image_path = PILOT / "images" / item["image"]
            if not image_path.exists():
                raise FileNotFoundError(image_path)
            target = media_dir / item["image"]
            if not target.exists():
                shutil.copy2(image_path, target)
            _upsert_asset(db, project.id, scene.id, "image", target, "image/png",
                          metadata={"provider": "Codex built-in image_gen", "symbolic_illustration": True})
        timings.append({"id": scene.id, "frames": frames, "captions": captions})
    db.commit()
    duration = sum(x["frames"] for x in timings) / FPS
    write_json(project_dir / "sentence-timings.json", timings)
    write_json(project_dir / "pilot-usage.json", {"speech_chars": chars, "speech_sentences": len(lines),
               "image_count": 6, "elapsed_media_seconds": round(time.perf_counter() - started, 2),
               "billed_cost_usd": None, "text_generation": script["editorial_mode"]})
    print(f"Measured duration: {duration:.3f}s", flush=True)
    if not 180 <= duration <= 300:
        raise ValueError("Duration outside 3-5 minutes. Review script/speed before rendering.")
    emit_event(db, project.id, "media", f"14 段真实配音完成，时长 {duration:.1f} 秒", 0.8)


def master_audio(export_dir: Path) -> None:
    manifest_path = export_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("audio_mastering"):
        return
    originals = export_dir.parent / "mastering-originals"
    originals.mkdir(exist_ok=True)
    # Measured pilot peaks leave > 8 dB of headroom in the MP4. These fixed gains
    # are for this reviewed pilot, not a loudness policy for arbitrary uploads.
    gains = {"video.mp4": 6, "narration.mp3": 3}
    for filename, gain in gains.items():
        source = export_dir / filename
        backup = originals / f"{source.stem}-{_hash_file(source)[:16]}{source.suffix}"
        if not backup.exists():
            shutil.copy2(source, backup)
        target = export_dir / f"{source.stem}.mastered{source.suffix}"
        args = ["ffmpeg", "-y", "-v", "error", "-i", str(backup)]
        if source.suffix == ".mp4":
            args += ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac",
                     "-b:a", "192k", "-movflags", "+faststart"]
        else:
            args += ["-c:a", "libmp3lame", "-b:a", "192k"]
        subprocess.run(args + ["-af", f"volume={gain}dB", str(target)], check=True, capture_output=True)
        target.replace(source)
    manifest["audio_mastering"] = {"gain_db": gains, "video_frames": "stream copied unchanged",
                                    "originals_preserved": True}
    manifest["files"] = {p.name: {"bytes": p.stat().st_size, "sha256": _hash_file(p)}
                         for p in export_dir.iterdir() if p.is_file() and p.name != "manifest.json"}
    write_json(manifest_path, manifest)
    print("Pilot audio mastered; original exports preserved outside publishing package.", flush=True)


def render(db, settings, project: Project, script: dict, preview_only: bool = False) -> None:
    project_dir = settings.data_dir.resolve() / "projects" / project.id
    timings = json.loads((project_dir / "sentence-timings.json").read_text(encoding="utf-8"))
    input_path, export_dir = prepare_render_input(db, settings, project)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    for item, timing, editorial in zip(payload["scenes"], timings, script["scenes"], strict=True):
        item["captions"] = timing["captions"]
        item["durationInFrames"] = timing["frames"]
        item["sourceLabel"] = "依据：" + editorial["references"][0] + (" · 本集解读" if editorial["claim_type"] == "interpretation" else "")
    payload["aiVoiceDisclosure"] = "AI 配音 · AI 意象插画 · 含剧透"
    write_json(input_path, payload)
    project.status = ProjectStatus.rendering
    db.commit()
    subprocess.run([shutil.which("npm") or "npm", "--workspace", "@content-agent/video", "run", "render",
                    "--", "--input", str(input_path.resolve()), "--output", str(export_dir.resolve())]
                   + (["--preview"] if preview_only else []),
                   cwd=ROOT, check=True)
    if preview_only:
        print(f"Preview: {export_dir / 'preview.png'}", flush=True)
        return
    # Only the base publishing-copy helper is used; no mock text/media generation.
    _write_exports(db, settings, project, export_dir, MockTextProvider())
    master_audio(export_dir)
    captions = []
    cursor = 0
    for timing in timings:
        captions.extend({**c, "start": c["start"] + cursor / FPS, "end": c["end"] + cursor / FPS}
                        for c in timing["captions"])
        cursor += timing["frames"]
    (export_dir / "captions.srt").write_text(_to_srt(captions), encoding="utf-8-sig")
    script_lines = [f"# 《{script['title']}》：{script['thesis']}", "", script["editorial_mode"], ""]
    sources = ["# 试播内容依据", "", script["source_edition"], "",
               "事实根据原著核对；观点属于本集解读，不代表唯一结论。全部中文旁白为转述或原创分析，不冒充某个中文译本的引文。", ""]
    for index, item in enumerate(script["scenes"], 1):
        script_lines.extend([f"## {index:02d} · {item['title']}", "", "".join(item["lines"]), ""])
        refs = "；".join(f"[{r}]({script['source_url']}#{CHAPTERS[r]})" for r in item["references"])
        sources.extend([f"- {index:02d} {item['title']}（{item['claim_type']}）：{refs}"])
    (export_dir / "script.md").write_text("\n".join(script_lines), encoding="utf-8")
    (export_dir / "sources.md").write_text("\n".join(sources), encoding="utf-8")
    (export_dir / "publishing-copy.md").write_text(
        "# 《罪与罚》：谁给了你伤害别人的权利？\n\n"
        "他拿到了钱，却没有用来救人。他想证明自己非凡，却把自己与他人隔绝。\n\n"
        "从故事框架出发，用两个细节讨论《罪与罚》中的自我授权："
        "当我们确信自己正确，是否还允许承担代价的人说不？\n\n"
        "名著里的困境 · 试播 01。含关键情节与结局剧透。观点为本集解读，原著定位见 sources.md。\n\n"
        "本视频使用 AI 合成配音和 AI 生成意象插画，画面不是历史影像或影视改编素材。\n\n"
        "#罪与罚 #陀思妥耶夫斯基 #世界名著 #文学解读 #读书\n", encoding="utf-8")
    shutil.copy2(PILOT / "image-prompts.json", export_dir / "image-prompts.json")
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["models"]["text"] = "Codex conversation: agent-authored, source-checked pilot"
    manifest["models"]["image"] = "Codex built-in image_gen (model not selected by runner)"
    manifest["editorial_mode"] = script["editorial_mode"]
    manifest["caption_alignment"] = "sentence WAV durations, frame-aligned scene boundaries"
    manifest["duration_seconds"] = cursor / FPS
    manifest["estimated_cost_usd"] = None
    manifest["files"] = {p.name: {"bytes": p.stat().st_size, "sha256": _hash_file(p)}
                         for p in export_dir.iterdir() if p.is_file() and p.name != "manifest.json"}
    write_json(export_dir / "manifest.json", manifest)
    project.status = ProjectStatus.completed
    db.commit()
    emit_event(db, project.id, "complete", "《罪与罚》试播视频与发布包已完成", 1)
    print(json.dumps({"project_id": project.id, "exports": str(export_dir.resolve())}, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["media", "preview", "render", "master", "all"], default="all")
    parser.add_argument("--reviewed", action="store_true", help="The supplied fixed pilot has been editorially reviewed")
    args = parser.parse_args()
    if not args.reviewed:
        parser.error("Review examples/crime-and-punishment-pilot.json first, then pass --reviewed")
    if Path.cwd().resolve() != ROOT:
        parser.error("Run from repository root")
    settings = get_settings()
    if settings.resolved_provider != "openai" or not settings.openai_api_key:
        raise ValueError("Real OpenAI speech is required. Mock fallback is not allowed.")
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    init_db()
    with SessionLocal() as db:
        project = create_project(db, settings, script)
        print(f"Project: {project.id}", flush=True)
        if args.stage in {"media", "all"}:
            media(db, settings, project, script)
        if args.stage in {"preview", "render", "all"}:
            render(db, settings, project, script, preview_only=args.stage == "preview")
        if args.stage == "master":
            master_audio(settings.data_dir.resolve() / "projects" / project.id / "exports")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
