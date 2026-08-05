from __future__ import annotations

import argparse
import sys
import time

from .config import get_settings
from .database import SessionLocal, init_db
from .services.jobs import claim_next_job
from .services.providers import make_providers
from .services.workflow import fail_job, process_job


def run_once() -> bool:
    settings = get_settings()
    text_provider, image_provider, speech_provider = make_providers(settings)
    with SessionLocal() as db:
        job = claim_next_job(db)
        if not job:
            return False
        try:
            process_job(db, settings, job, text_provider, image_provider, speech_provider)
        except Exception as exc:  # the worker must persist every failure
            db.rollback()
            fail_job(db, job, exc)
        return True


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Literary content agent worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--app-dir", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    init_db()
    if args.once:
        run_once()
        return
    print("内容 Agent worker 已启动。按 Ctrl+C 停止。", flush=True)
    try:
        while True:
            if not run_once():
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
