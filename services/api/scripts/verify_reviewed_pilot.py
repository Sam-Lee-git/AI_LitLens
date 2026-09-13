"""Read-only media/content verification plus QA frame extraction for the fixed pilot."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PILOT = ROOT / "data" / "pilots" / "crime-and-punishment"


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        text=True, encoding="utf-8"))


def timestamp(text: str) -> float:
    hours, minutes, seconds, millis = map(int, re.split(r"[:,]", text))
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def main() -> None:
    state = json.loads((PILOT / "state.json").read_text(encoding="utf-8"))
    project = ROOT / "data" / "projects" / state["project_id"]
    exports = project / "exports"
    manifest = json.loads((exports / "manifest.json").read_text(encoding="utf-8"))
    timings = json.loads((project / "sentence-timings.json").read_text(encoding="utf-8"))
    required = ["video.mp4", "narration.mp3", "captions.srt", "cover.png", "storyboard.json",
                "sources.md", "publishing-copy.md", "script.md", "image-prompts.json"]
    for filename in required:
        path = exports / filename
        assert path.is_file() and path.stat().st_size > 0, filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["files"][filename]["sha256"], filename
    video_probe = probe(exports / "video.mp4")
    video = next(s for s in video_probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in video_probe["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"], video["codec_name"]) == (1080, 1920, "30/1", "h264")
    assert audio["codec_name"] == "aac"
    # FFprobe names full-range 8-bit 4:2:0 "yuvj420p"; both are valid H.264 outputs.
    assert video["pix_fmt"] in {"yuv420p", "yuvj420p"}
    duration = float(video_probe["format"]["duration"])
    expected = sum(t["frames"] for t in timings) / 30
    assert 180 <= duration <= 300 and abs(duration - expected) < .1
    assert abs(float(audio["duration"]) - expected) < .1
    narration_duration = float(probe(exports / "narration.mp3")["format"]["duration"])
    assert abs(narration_duration - expected) < .1
    intervals = re.findall(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})",
                           (exports / "captions.srt").read_text(encoding="utf-8-sig"))
    assert len(intervals) == sum(len(t["captions"]) for t in timings) == 49
    cursor = 0.0
    for begin, finish in intervals:
        start, end = timestamp(begin), timestamp(finish)
        assert abs(start - cursor) <= .002 and start < end <= duration + .002
        cursor = end
    assert abs(cursor - expected) <= .002
    storyboard = json.loads((exports / "storyboard.json").read_text(encoding="utf-8"))
    assert len(storyboard["scenes"]) == 14
    assert all(s["verified"] and s["citations"] for s in storyboard["scenes"])
    prompts = json.loads((exports / "image-prompts.json").read_text(encoding="utf-8"))
    assert len(prompts["images"]) == 6
    # Decode the entire result: container metadata alone cannot prove playability.
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(exports / "video.mp4"), "-f", "null", "-"],
                   check=True, capture_output=True)
    volume_output = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(exports / "video.mp4"),
                                   "-vn", "-af", "volumedetect", "-f", "null", "-"],
                                  check=True, capture_output=True, text=True, encoding="utf-8").stderr
    mean = re.search(r"mean_volume: ([-\d.]+) dB", volume_output)
    peak = re.search(r"max_volume: ([-\d.]+) dB", volume_output)
    assert mean and peak and -45 < float(mean[1]) < -3, "Missing or unusably quiet audio"
    qa = project / "qa"
    qa.mkdir(exist_ok=True)
    cursor_frames = 0
    frame_paths = []
    for index, timing in enumerate(timings):
        seconds = (cursor_frames + min(120, timing["frames"] // 2)) / 30
        target = qa / f"scene-{index + 1:02d}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(seconds), "-i", str(exports / "video.mp4"),
                        "-frames:v", "1", str(target)], check=True, capture_output=True)
        frame_paths.append(str(target))
        cursor_frames += timing["frames"]
    report = {"passed": True, "project_id": state["project_id"], "duration_seconds": duration,
              "resolution": "1080x1920", "fps": 30, "codecs": ["h264", "aac"],
              "pixel_format": video["pix_fmt"], "color_range": video.get("color_range"),
              "full_decode": "passed", "sentences": len(intervals), "scenes": len(timings),
              "mean_volume_db": float(mean[1]), "peak_volume_db": float(peak[1]),
              "checks": ["manifest hashes", "required exports", "frame-aligned duration",
                         "narration duration", "contiguous caption boundaries", "source references",
                         "six saved image prompts", "full decode", "non-silent audio"],
              "qa_frames": frame_paths,
              "scope": "Reviewed pilot; not unattended title-to-video acceptance or three-video acceptance"}
    (qa / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
