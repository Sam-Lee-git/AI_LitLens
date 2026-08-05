from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Job, JobStatus, ProjectEvent


def payload_hash(job_type: str, payload: dict) -> str:
    encoded = json.dumps({"type": job_type, "payload": payload}, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def emit_event(
    db: Session,
    project_id: str,
    kind: str,
    message: str,
    progress: float = 0.0,
    data: dict | None = None,
) -> None:
    db.add(
        ProjectEvent(
            project_id=project_id,
            kind=kind,
            message=message,
            progress=max(0.0, min(1.0, progress)),
            data=data or {},
        )
    )
    db.commit()


def enqueue_job(db: Session, project_id: str, job_type: str, payload: dict) -> Job:
    digest = payload_hash(job_type, payload)
    existing = db.scalar(
        select(Job).where(
            Job.project_id == project_id,
            Job.job_type == job_type,
            Job.input_hash == digest,
        )
    )
    if existing and existing.status != JobStatus.failed:
        return existing
    if existing and existing.status == JobStatus.failed:
        db.delete(existing)
        db.commit()
    job = Job(project_id=project_id, job_type=job_type, input_hash=digest, payload=payload)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(
            select(Job).where(
                Job.project_id == project_id,
                Job.job_type == job_type,
                Job.input_hash == digest,
            )
        )
    db.refresh(job)
    emit_event(db, project_id, "job_queued", f"任务已加入队列：{job_type}", data={"job_id": job.id})
    return job


def claim_next_job(db: Session) -> Job | None:
    job = db.scalar(
        select(Job).where(Job.status == JobStatus.queued).order_by(Job.created_at).limit(1)
    )
    if not job:
        return None
    job.status = JobStatus.running
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    job.error = None
    db.commit()
    db.refresh(job)
    return job
