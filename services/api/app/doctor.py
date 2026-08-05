from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys

from openai import OpenAI

from .config import get_settings


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="检查文学内容 Agent 本地环境")
    parser.add_argument("--app-dir", default=None, help=argparse.SUPPRESS)
    parser.parse_args()
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python 3.12+", sys.version_info >= (3, 12), sys.version.split()[0]))
    for command in ("node", "npm", "ffmpeg", "ffprobe"):
        resolved = shutil.which(command)
        checks.append((command, bool(resolved), resolved or "未找到"))
    if settings.openai_api_key:
        try:
            client = OpenAI(api_key=settings.openai_api_key)
            available = []
            for model in (settings.text_model, settings.image_model, settings.speech_model):
                client.models.retrieve(model)
                available.append(model)
            checks.append(("OpenAI 模型权限", True, "、".join(available)))
            checks.append(("GPT Image 组织验证", True, "图片模型可见；最终状态以首次生成请求为准"))
        except Exception as exc:
            checks.append(("OpenAI 模型权限", False, str(exc)[:180]))
    else:
        checks.append(("OpenAI API", True, "未配置，将使用演示提供器"))
    try:
        connection = sqlite3.connect(settings.data_dir / "doctor.db")
        connection.execute("select 1")
        connection.close()
        (settings.data_dir / "doctor.db").unlink(missing_ok=True)
        checks.append(("本地数据目录", True, str(settings.data_dir.resolve())))
    except OSError as exc:
        checks.append(("本地数据目录", False, str(exc)))
    width = max(len(name) for name, _, _ in checks)
    print("\nAI 文学解读内容 Agent 环境检查\n")
    for name, ok, detail in checks:
        print(f"{'✓' if ok else '!'} {name:<{width}}  {detail}")
    hard_failures = [name for name, ok, _ in checks if not ok]
    if hard_failures:
        raise SystemExit(1)
    if not settings.openai_api_key:
        print("\n提示：当前可以完整体验工作流，但插画和语音是演示占位内容。")


if __name__ == "__main__":
    main()
