"""Render an exported PPTX with a reviewed narration script using AI LitLens.

The source deck stays local. Only narration sentences go to the configured
OpenAI speech provider. Hash-cached speech is reused after interruptions.
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
from app.config import get_settings  # noqa: E402
from app.services.providers import OpenAISpeechProvider  # noqa: E402
from app.services.workflow import _to_srt  # noqa: E402

RATE, FPS = 48000, 30


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout


def probe(path: Path) -> dict:
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def line_audio(settings, directory: Path, text: str) -> tuple[Path, bool]:
    key = hashlib.sha256(json.dumps([settings.speech_model, settings.speech_voice, text], ensure_ascii=False).encode()).hexdigest()
    mp3, wav = directory / f"{key}.mp3", directory / f"{key}.wav"
    reused = mp3.exists()
    if not reused:
        temporary = directory / f"{key}.partial.mp3"
        # The SDK performs at most two retries for transient failures. No outer retry loop.
        OpenAISpeechProvider(settings).synthesize(text, temporary)
        probe(temporary)
        temporary.replace(mp3)
    if not wav.exists():
        temporary = directory / f"{key}.partial.wav"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(RATE),
             "-c:a", "pcm_s16le", str(temporary)])
        temporary.replace(wav)
    with wave.open(str(wav)) as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, RATE) or audio.getnframes() < RATE // 4:
            raise ValueError("Invalid speech cache; inspect the cached file before retrying.")
    return wav, reused


def prepare(work: Path, script: dict, deck: dict) -> None:
    settings = get_settings()
    if not settings.openai_api_key or settings.resolved_provider != "openai":
        raise RuntimeError("A configured OpenAI key/provider is required. No silent or mock fallback.")
    lines = list(dict.fromkeys(line for slide in script["slides"] for line in slide["lines"]))
    if any(not 1 <= len(line) <= 100 for line in lines):
        raise ValueError("Narration sentences must be 1-100 characters for readable subtitles.")
    if settings.speech_model not in {"tts-1", "tts-1-hd"}:
        raise ValueError("This runner's speech budget estimate supports tts-1 and tts-1-hd only.")
    chars = sum(map(len, lines))
    rate = 30 if settings.speech_model == "tts-1-hd" else 15
    estimate = chars * rate / 1_000_000
    if estimate > min(1.0, settings.project_budget_usd):
        raise ValueError("Speech estimate exceeds the configured project or $1 run limit.")
    print(f"Speech: {len(lines)} sentences, {chars} characters, estimated ${estimate:.4f} before retries", flush=True)
    cache, public, exports = work / "speech-cache", work / "public", work / "exports"
    for directory in (cache, public, exports): directory.mkdir(parents=True, exist_ok=True)
    started, results, reused_count = time.perf_counter(), {}, 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(line_audio, settings, cache, line): line for line in lines}
        for future in as_completed(futures):
            audio, reused = future.result()
            results[futures[future]] = audio
            reused_count += int(reused)
            print(f"Speech {len(results)}/{len(lines)} {'cached' if reused else 'generated'}", flush=True)
    payload = {"title": script["title"], "audioSrc": "narration.wav", "publicDir": str(public), "slides": []}
    full_pcm, subtitles, chapters = bytearray(), [], []
    script_md = [f"# {script['title']}", "", "本视频使用 AI 合成配音。", "", script["editorialMode"], ""]
    for slide in script["slides"]:
        offset = len(full_pcm) / (RATE * 2)
        pcm = bytearray(bytes(round(RATE * .55) * 2))
        captions = []
        for line in slide["lines"]:
            start = len(pcm) / (RATE * 2)
            with wave.open(str(results[line])) as audio: pcm.extend(audio.readframes(audio.getnframes()))
            end = len(pcm) / (RATE * 2)
            captions.append({"start": start, "end": end, "text": line})
            pcm.extend(bytes(round(RATE * .18) * 2))
        pcm.extend(bytes(round(RATE * .5) * 2))
        frames = math.ceil(len(pcm) / 2 / (RATE / FPS))
        pcm.extend(bytes(frames * (RATE // FPS) * 2 - len(pcm)))
        image_name = f"slide-{slide['number']:02d}.png"
        shutil.copy2(work / "slides" / image_name, public / image_name)
        payload["slides"].append({"number": slide["number"], "title": slide["title"], "imageSrc": image_name,
                                  "durationInFrames": frames, "captions": captions})
        subtitles.extend({**c, "start": c["start"] + offset, "end": c["end"] + offset} for c in captions)
        chapters.append({"number": slide["number"], "title": slide["title"], "start": offset, "end": offset + frames / FPS})
        script_md.extend([f"## 第{slide['number']}页 {slide['title']}", "", *slide["lines"], ""])
        full_pcm.extend(pcm)
    duration = len(full_pcm) / (RATE * 2)
    raw_audio = work / "narration-raw.wav"
    with wave.open(str(raw_audio), "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(RATE); audio.writeframes(full_pcm)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(raw_audio), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-ar", str(RATE), "-ac", "1", "-t", str(duration), "-c:a", "pcm_s16le", str(public / "narration.wav")])
    run(["ffmpeg", "-y", "-v", "error", "-i", str(public / "narration.wav"), "-c:a", "libmp3lame", "-b:a", "192k",
         str(exports / "narration.mp3")])
    write_json(work / "render-input.json", payload)
    write_json(exports / "storyboard.json", {"title": script["title"], "sourceSha256": deck["sourceSha256"],
               "slides": payload["slides"], "narration": script["slides"], "chapters": chapters})
    write_json(work / "captions.json", subtitles)
    (exports / "captions.srt").write_text(_to_srt(subtitles), encoding="utf-8-sig")
    (exports / "script.md").write_text("\n".join(script_md), encoding="utf-8")
    (exports / "sources.md").write_text(f"# 来源\n\n用户提供：{deck['sourceName']}\n\n"
        f"SHA256: {deck['sourceSha256']}\n\n实际{len(deck['slides'])}页，保留文件中的顺序和版式。\n\n{script['editorialMode']}\n\n"
        "正文中的示意数据与研讨假设不代表研究院实测或部署情况。未独立复核PPT中的全部外部来源。\n"
        "页面中的模型名称与链接按原PPT保留，旁白不将其扩写为已核实的产品结论。\n", encoding="utf-8")
    chapter_lines = [f"{int(c['start']) // 60:02d}:{int(c['start']) % 60:02d} {c['title']}" for c in chapters]
    (exports / "chapters.txt").write_text("\n".join(chapter_lines), encoding="utf-8")
    shutil.copy2(work / "slides" / "slide-01.png", exports / "cover.png")
    write_json(work / "media-state.json", {"sourceSha256": deck["sourceSha256"], "scriptSha256": digest(work / "narration.json"),
               "durationSeconds": duration, "sentences": len(subtitles), "speechCharacters": chars,
               "estimatedSpeechCostUsd": estimate, "billedCostUsd": None, "cachedSentences": reused_count,
               "speechModel": settings.speech_model, "voice": settings.speech_voice,
               "elapsedSeconds": round(time.perf_counter() - started, 2)})
    print(f"Measured duration: {duration:.3f}s; {len(payload['slides'])} slides", flush=True)


def render_cached_slides(work: Path) -> None:
    """Render only distinct Remotion frames; FFmpeg holds them at exact 30fps timings."""
    stills = work / "render-stills"
    subprocess.run([shutil.which("npm") or "npm", "--workspace", "@content-agent/video", "run", "render:presentation", "--",
                    "--input", str(work / "render-input.json"), "--output", str(stills), "--stills"], cwd=ROOT, check=True)
    pages = json.loads((stills / "timelines.json").read_text(encoding="utf-8"))
    segments = work / "segments"
    segments.mkdir(exist_ok=True)
    for page in pages:
        assert sum(i["frames"] for i in page["intervals"]) == page["durationInFrames"]
        filename = f"page-{page['number']:02d}.mp4"
        output = segments / filename
        identity = hashlib.sha256(json.dumps([page, {i["file"]: digest(stills / i["file"])
            for i in page["intervals"]}, "h264-crf18-veryfast-stillimage-fade10-v1"], sort_keys=True).encode()).hexdigest()
        state_path = output.with_suffix(".json")
        if output.exists() and state_path.exists() and json.loads(state_path.read_text())["inputHash"] == identity:
            print(f"Encode page {page['number']}/{len(pages)} cached", flush=True)
            continue
        entries = ["ffconcat version 1.0"]
        for item in page["intervals"]:
            entries += [f"file '{item['file']}'", "option framerate 30", f"duration {item['frames'] / FPS:.9f}"]
        entries += [f"file '{page['intervals'][-1]['file']}'", "option framerate 30"]
        concat_path = stills / f"page-{page['number']}.ffconcat"
        concat_path.write_text("\n".join(entries), encoding="utf-8")
        filters = f"fps=30,fade=t=in:s=0:n=10:color=white,fade=t=out:s={page['durationInFrames'] - 10}:n=10:color=white,format=yuv420p"
        print(f"Encode page {page['number']}/{len(pages)}", flush=True)
        pending = output.with_suffix(".partial.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_path),
             "-vf", filters, "-frames:v", str(page["durationInFrames"]), "-an", "-c:v", "libx264", "-crf", "18",
             "-preset", "veryfast", "-tune", "stillimage", "-threads", "4", str(pending)])
        video = next(s for s in probe(pending)["streams"] if s["codec_type"] == "video")
        assert int(video["nb_frames"]) == page["durationInFrames"]
        pending.replace(output)
        write_json(state_path, {"inputHash": identity})
    (segments / "all.ffconcat").write_text("ffconcat version 1.0\n" + "\n".join(
        f"file 'page-{p['number']:02d}.mp4'" for p in pages), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(segments / "all.ffconcat"),
         "-i", str(work / "public" / "narration.wav"), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(work / "exports" / "video.rendering.mp4")])


def render(work: Path, preview: bool, cached: bool = False) -> None:
    state = json.loads((work / "media-state.json").read_text(encoding="utf-8"))
    if state["scriptSha256"] != digest(work / "narration.json"):
        raise ValueError("Narration changed. Run --stage media to update only changed speech.")
    command = [shutil.which("npm") or "npm", "--workspace", "@content-agent/video", "run", "render:presentation", "--",
               "--input", str(work / "render-input.json"), "--output", str(work / ("qa" if preview else "exports"))]
    if preview: command.append("--preview")
    if cached:
        render_cached_slides(work)
    else:
        subprocess.run(command, cwd=ROOT, check=True)
    if preview: return
    storyboard = json.loads((work / "exports" / "storyboard.json").read_text(encoding="utf-8"))
    metadata = [";FFMETADATA1", f"title={storyboard['title']}", "comment=AI synthesized Chinese narration; user-provided PowerPoint slides"]
    for chapter in storyboard["chapters"]:
        metadata += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(chapter['start'] * 1000)}",
                     f"END={round(chapter['end'] * 1000)}", f"title={chapter['title']}"]
    metadata_path = work / "chapters.ffmetadata"
    metadata_path.write_text("\n".join(metadata), encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(work / "exports" / "video.rendering.mp4"),
         "-i", str(metadata_path), "-map", "0", "-map_metadata", "1", "-map_chapters", "1", "-c", "copy",
         "-movflags", "+faststart", str(work / "exports" / "video.pending.mp4")])
    verify(work, work / "exports" / "video.pending.mp4")
    (work / "exports" / "video.pending.mp4").replace(work / "exports" / "video.mp4")
    # Intermediate renders stay in the private work directory, outside the delivery bundle.
    (work / "exports" / "video.rendering.mp4").replace(work / "video-unmuxed.mp4")
    manifest = {**state, "resolution": "1920x1080", "fps": FPS, "codecs": ["h264", "aac"],
                "renderEngine": "AI LitLens / Remotion PresentationVideo" + (" + cached-frame FFmpeg encoding" if cached else ""), "aiVoiceDisclosure": True,
                "files": {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)}
                          for p in (work / "exports").iterdir() if p.is_file() and p.name != "manifest.json"}}
    write_json(work / "exports" / "manifest.json", manifest)
    print(f"Completed: {work / 'exports' / 'video.mp4'}", flush=True)


def verify(work: Path, video_path: Path | None = None) -> None:
    state = json.loads((work / "media-state.json").read_text(encoding="utf-8"))
    target = video_path or work / "exports" / "video.mp4"
    data = probe(target)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"], video["codec_name"]) == (1920, 1080, "30/1", "h264")
    assert audio["codec_name"] == "aac"
    assert abs(float(data["format"]["duration"]) - state["durationSeconds"]) < .15
    assert abs(float(audio["duration"]) - state["durationSeconds"]) < .15
    subtitles = json.loads((work / "captions.json").read_text(encoding="utf-8"))
    previous_end = 0
    for caption in subtitles:
        assert previous_end <= caption["start"] < caption["end"] <= state["durationSeconds"]
        previous_end = caption["end"]
    print("Verifying full video decode...", flush=True)
    run(["ffmpeg", "-v", "error", "-i", str(target), "-f", "null", "-"])
    volume = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(target), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                            check=True, capture_output=True, text=True, encoding="utf-8").stderr
    import re
    mean = re.search(r"mean_volume: ([-\d.]+) dB", volume)
    assert mean and -35 < float(mean[1]) < -5, "Missing or unusably quiet narration"
    write_json(work / "qa" / "verification.json", {"passed": True, "durationSeconds": state["durationSeconds"],
               "resolution": "1920x1080", "fps": 30, "codecs": ["h264", "aac"], "sentences": len(subtitles),
               "fullDecode": True, "meanVolumeDb": float(mean[1]), "captionTiming": "measured sentence WAV durations"})
    print("Verification passed.", flush=True)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=["media", "preview", "render", "render-fast", "verify", "all"], default="all")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    script = json.loads((work / "narration.json").read_text(encoding="utf-8"))
    deck = json.loads((work / "deck.json").read_text(encoding="utf-8"))
    if script["sourceSha256"] != deck["sourceSha256"] or digest(work / "source-snapshot.pptx") != deck["sourceSha256"]:
        raise ValueError("Deck and narration source hashes differ.")
    if [s["number"] for s in script["slides"]] != [s["number"] for s in deck["slides"]]:
        raise ValueError("Narration must cover all exported slides in the original order.")
    if args.stage in {"media", "all"}: prepare(work, script, deck)
    if args.stage in {"preview", "all"}: render(work, True)
    if args.stage in {"render", "all"}: render(work, False)
    if args.stage == "render-fast": render(work, False, cached=True)
    if args.stage == "verify": verify(work)


if __name__ == "__main__":
    main()
