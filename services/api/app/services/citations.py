from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Citation, Scene, SourceBlock


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("，。！？；：,.!?;:'\"")


def verify_citation(citation: Citation, block: SourceBlock) -> tuple[bool, float]:
    if citation.claim_type == "interpretation":
        return (bool(block.text.strip()), 0.82 if block.text.strip() else 0.0)
    quote = _normalize(citation.quote)
    body = _normalize(block.text)
    if not quote:
        return False, 0.0
    if quote in body:
        return True, 1.0
    ratio = SequenceMatcher(None, quote, body[: max(len(quote) * 5, 500)]).ratio()
    return ratio >= 0.35, round(ratio, 3)


def verify_storyboard(db: Session, project_id: str) -> list[str]:
    errors: list[str] = []
    scenes = list(
        db.scalars(select(Scene).where(Scene.project_id == project_id).order_by(Scene.ordinal))
    )
    for scene in scenes:
        if not scene.citations:
            scene.verified = False
            errors.append(f"{scene.title} 没有关联来源。")
            continue
        scene_ok = True
        for citation in scene.citations:
            block = db.get(SourceBlock, citation.block_id)
            if not block or block.project_id != project_id:
                citation.verified = False
                citation.confidence = 0.0
                scene_ok = False
                errors.append(f"{scene.title} 引用了不存在的来源片段。")
                continue
            verified, confidence = verify_citation(citation, block)
            citation.verified = verified
            citation.confidence = confidence
            if not verified:
                scene_ok = False
                errors.append(f"{scene.title} 的{citation.claim_type}引用无法在原文中核对。")
        scene.verified = scene_ok
    db.commit()
    return errors
