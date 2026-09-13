from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def assert_video(video: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    probe = json.loads(result.stdout)
    video_stream = next(item for item in probe["streams"] if item["codec_type"] == "video")
    audio_stream = next(item for item in probe["streams"] if item["codec_type"] == "audio")
    duration = float(probe["format"]["duration"])
    assert video_stream["codec_name"] == "h264"
    assert (video_stream["width"], video_stream["height"]) == (1080, 1920)
    assert video_stream["avg_frame_rate"] == "30/1"
    assert audio_stream["codec_name"] == "aac"
    assert 180 <= duration <= 300, f"视频时长 {duration:.1f}s 不在 3–5 分钟内"
    return {"duration_seconds": round(duration, 2), "bytes": video.stat().st_size}


def run_project(client, run_once, iteration: int) -> dict:
    response = client.post(
        "/projects",
        json={
            "title": f"公共领域文学验收 {iteration}",
            "description": "mock 书名直达 E2E",
            "auto_analyze": True,
        },
    )
    response.raise_for_status()
    project_id = response.json()["id"]
    assert run_once()
    project = client.get(f"/projects/{project_id}").json()
    assert project["status"] == "angles_ready"
    client.put(
        f"/projects/{project_id}/angle", json={"angle_id": project["angles"][0]["id"]}
    ).raise_for_status()
    assert run_once()
    board = client.get(f"/projects/{project_id}/storyboard").json()
    assert 12 <= len(board["scenes"]) <= 18
    assert all(scene["verified"] for scene in board["scenes"])
    client.post(
        f"/projects/{project_id}/storyboard/approve", json={"override_budget": False}
    ).raise_for_status()
    assert run_once()
    project = client.get(f"/projects/{project_id}").json()
    if project["status"] != "completed":
        raise RuntimeError(f"渲染未完成，项目状态：{project['status']}")
    exports = client.get(f"/projects/{project_id}/exports").json()["items"]
    names = {item["name"] for item in exports}
    required = {
        "video.mp4",
        "narration.mp3",
        "captions.srt",
        "cover.png",
        "storyboard.json",
        "sources.md",
        "publishing-copy.md",
        "manifest.json",
    }
    assert required <= names, f"发布包缺少：{sorted(required - names)}"
    data_dir = Path(os.environ["CONTENT_AGENT_DATA_DIR"])
    video_result = assert_video(data_dir / "projects" / project_id / "exports" / "video.mp4")
    return {"project_id": project_id, "files": len(names), **video_result}


def rerender_project(client, run_once, project_id: str) -> dict:
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Asset

    def current_assets() -> dict[tuple[str | None, str], str]:
        with SessionLocal() as db:
            return {
                (asset.scene_id, asset.kind): asset.checksum
                for asset in db.scalars(
                    select(Asset).where(Asset.project_id == project_id, Asset.stale.is_(False))
                )
            }

    board = client.get(f"/projects/{project_id}/storyboard").json()
    changed_scene_id = board["scenes"][0]["id"]
    before = current_assets()
    board["scenes"][0]["narration"] += "这次局部修改只触发当前场景的重新配音。"
    saved = client.put(f"/projects/{project_id}/storyboard", json=board)
    saved.raise_for_status()
    assert saved.json()["scenes"][0]["verified"] is False
    reviewed = client.post(
        f"/projects/{project_id}/scenes/{changed_scene_id}/regenerate",
        json={"target": "verify", "instruction": ""},
    )
    reviewed.raise_for_status()
    assert reviewed.json()["verified"] is True
    client.post(
        f"/projects/{project_id}/storyboard/approve", json={"override_budget": False}
    ).raise_for_status()
    assert run_once()
    project = client.get(f"/projects/{project_id}").json()
    assert project["status"] == "completed"
    after = current_assets()
    changed = (changed_scene_id, "audio")
    assert before[changed] != after[changed]
    for key, checksum in before.items():
        if key != changed:
            assert after[key] == checksum, f"未修改资源被重复生成：{key}"
    data_dir = Path(os.environ["CONTENT_AGENT_DATA_DIR"])
    video_result = assert_video(data_dir / "projects" / project_id / "exports" / "video.mp4")
    return {"project_id": project_id, "preserved_assets": len(before) - 1, **video_result}


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 mock 端到端渲染验收")
    parser.add_argument("--count", type=int, choices=range(1, 4), default=1)
    parser.add_argument(
        "--existing-project", default=None, help="对既有验收项目执行局部修改与重渲染"
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    data_dir = repo_root / "data" / "e2e"
    os.environ["CONTENT_AGENT_PROVIDER"] = "mock"
    os.environ["CONTENT_AGENT_DATA_DIR"] = str(data_dir)
    os.environ["CONTENT_AGENT_DATABASE_URL"] = (
        f"sqlite:///{(data_dir / 'content-agent.db').as_posix()}"
    )
    sys.path.insert(0, str(repo_root / "services" / "api"))

    from fastapi.testclient import TestClient

    from app.main import app
    from app.worker import run_once

    results = []
    with TestClient(app) as client:
        if args.existing_project:
            results.append(rerender_project(client, run_once, args.existing_project))
        else:
            for iteration in range(1, args.count + 1):
                results.append(run_project(client, run_once, iteration))
    print(json.dumps({"status": "passed", "projects": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
