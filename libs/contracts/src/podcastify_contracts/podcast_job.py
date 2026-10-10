from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Citation(BaseModel):
    source: str = Field(..., description="Source identifier, e.g., filename or doc id")
    page: int | None = Field(None, description="Page number if known")
    snippet: str | None = Field(None, description="Short supporting snippet")


class EpisodeSegment(BaseModel):
    title: str
    speaker: str = Field(default="Host")
    text: str
    citations: list[Citation] = Field(default_factory=list)
    voice: str | None = Field(
        default=None, description="Optional voice/persona identifier for TTS."
    )


class EpisodeArtifact(BaseModel):
    kind: str = Field(..., description="e.g. script_markdown, audio_mp3, transcript_txt")
    path: str = Field(..., description="Filesystem path or URL (later)")


class PodcastJobRequest(BaseModel):
    input_filename: str
    language: str = Field(default="en")
    style: str = Field(default="everyday")
    target_minutes: int = Field(default=8, ge=0, le=60)
    target_seconds: int = Field(default=0, ge=0, le=59)
    pause_at_script: bool = Field(
        default=False, description="Pause after script generation for human review before TTS."
    )


class PodcastJobResult(BaseModel):
    job_id: str
    status: JobStatus
    title: str | None = None
    segments: list[EpisodeSegment] = Field(default_factory=list)
    artifacts: list[EpisodeArtifact] = Field(default_factory=list)
    error: str | None = None


class ScriptReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ScriptReviewRequest(BaseModel):
    action: ScriptReviewAction = Field(default=ScriptReviewAction.APPROVE)
    segments: list[EpisodeSegment] | None = Field(
        default=None, description="Optional edited segments overriding the generated script."
    )
    notes: str | None = None


class ScriptReviewResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str
