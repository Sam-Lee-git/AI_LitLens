from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ProjectStatus


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    auto_analyze: bool = False


class SourceBlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ordinal: int
    locator: dict
    text: str


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    source_type: str
    title: str
    original_filename: str | None
    char_count: int
    created_at: datetime


class AngleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ordinal: int
    title: str
    hook: str
    thesis: str
    audience_value: str
    evidence_block_ids: list[str]


class CitationDraft(BaseModel):
    id: str | None = None
    block_id: str
    claim_type: Literal["fact", "quote", "interpretation"]
    quote: str = ""
    verified: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)


class CitationRead(CitationDraft):
    id: str
    locator: dict | None = None
    source_title: str | None = None


class SceneDraft(BaseModel):
    id: str | None = None
    ordinal: int
    title: str = Field(min_length=1, max_length=200)
    narration: str = Field(min_length=1, max_length=5000)
    on_screen_text: str = Field(default="", max_length=1000)
    visual_type: Literal["illustration", "quote_card", "text_card", "relationship_card"]
    visual_prompt: str = Field(default="", max_length=3000)
    duration_seconds: float = Field(default=12, ge=3, le=45)
    verified: bool = False
    revision: int = 1
    citations: list[CitationDraft] = Field(default_factory=list)


class SceneRead(SceneDraft):
    id: str
    citations: list[CitationRead]
    assets: list[dict] = Field(default_factory=list)


class StoryboardRead(BaseModel):
    project_id: str
    revision: int
    target_platform: str
    style: str
    speech_voice: Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    estimated_cost_usd: float
    scenes: list[SceneRead]


class StoryboardUpdate(BaseModel):
    revision: int
    target_platform: str = Field(max_length=32)
    style: str = Field(max_length=200)
    speech_voice: Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"] = "alloy"
    scenes: list[SceneDraft] = Field(min_length=1, max_length=24)


class AngleSelection(BaseModel):
    angle_id: str


class ApprovalRequest(BaseModel):
    override_budget: bool = False


class RegenerateRequest(BaseModel):
    target: Literal["narration", "visual", "audio", "verify"]
    instruction: str = Field(default="", max_length=1000)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    description: str
    status: ProjectStatus
    language: str
    target_platform: str
    style: str
    selected_angle_id: str | None
    storyboard_revision: int
    estimated_cost_usd: float
    created_at: datetime
    updated_at: datetime
    sources: list[SourceRead] = Field(default_factory=list)
    angles: list[AngleRead] = Field(default_factory=list)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    job_type: str
    status: str
    attempts: int
    error: str | None


class ExportItem(BaseModel):
    name: str
    size: int
    url: str


class ExportList(BaseModel):
    project_id: str
    items: list[ExportItem]


class AngleBatch(BaseModel):
    angles: list[dict]


class StoryboardBatch(BaseModel):
    scenes: list[SceneDraft]
