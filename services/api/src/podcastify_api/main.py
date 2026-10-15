from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from podcastify_contracts.podcast_job import (
    JobStatus,
    PodcastJobRequest,
    ScriptReviewAction,
    ScriptReviewRequest,
    ScriptReviewResponse,
)
from podcastify_podcast.infrastructure.storage import create_job_store
from pydantic import BaseModel, Field, ValidationError

from podcastify_api.queue import enqueue_dir, enqueue_file, enqueue_redis

app = FastAPI(title="Thinking in Code API")
log = logging.getLogger("podcastify_api")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path)


_load_env()

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
ASSETS_DIR = Path(__file__).resolve().parents[4] / "assets"
JOBS_DIR = DATA_DIR / "jobs"
PROCESSED_DIR = DATA_DIR / "processed"
FEEDBACK_DIR = DATA_DIR / "feedback"
QUEUE_DIR = Path(os.getenv("QUEUE_DIR", str(DATA_DIR / "queue")))
QUEUE_FILE = Path(os.getenv("QUEUE_FILE", str(QUEUE_DIR / "queue.jsonl")))
QUEUE_MODE = os.getenv("QUEUE_MODE", "dir").lower()
QUEUE_REDIS_URL = os.getenv("QUEUE_REDIS_URL", "redis://localhost:6379/0")
QUEUE_REDIS_KEY = os.getenv("QUEUE_REDIS_KEY", "podcastify:jobs")
API_KEY = os.getenv("API_KEY", "")
MAX_UPLOAD_BYTES = _env_int("UPLOAD_MAX_BYTES", 30 * 1024 * 1024)
IDEMPOTENCY_DIR = DATA_DIR / "idempotency"
ALLOWED_UPLOAD_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
ALLOWED_UPLOAD_EXTENSIONS = {".pdf"}
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,79}$")
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
UPLOAD_FILE_PARAM = File(...)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


def _ensure_data_dirs() -> None:
    for path in [
        DATA_DIR,
        JOBS_DIR,
        PROCESSED_DIR,
        FEEDBACK_DIR,
        IDEMPOTENCY_DIR,
        QUEUE_DIR,
        DATA_DIR / "research",
    ]:
        path.mkdir(parents=True, exist_ok=True)


_ensure_data_dirs()


def _init_logging() -> None:
    fmt = os.getenv("LOG_FORMAT", "plain").lower()
    if fmt == "json":
        logging.basicConfig(
            level=logging.INFO, format='{"level":"%(levelname)s","message":"%(message)s"}'
        )
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


_init_logging()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _status_path(job_id: str) -> Path:
    _validate_job_id(job_id)
    return _job_dir(job_id) / "status.json"


def _write_status(
    job_id: str,
    *,
    status: JobStatus,
    stage: str | None = None,
    detail: str | None = None,
    error: str | None = None,
    result_path: str | None = None,
) -> None:
    payload = {
        "job_id": job_id,
        "status": status.value,
        "stage": stage,
        "detail": detail,
        "error": error,
        "result_path": result_path,
        "updated_at": _now_iso(),
    }
    path = _status_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _validate_job_id(raw_job_id: str | None) -> str:
    if not raw_job_id:
        return f"job-{uuid.uuid4().hex[:8]}"
    if not JOB_ID_PATTERN.fullmatch(raw_job_id):
        raise HTTPException(
            status_code=422,
            detail="Invalid job_id. Use 3-80 chars: letters, numbers, underscore, hyphen.",
        )
    return raw_job_id


def _is_pdf_content(content: bytes) -> bool:
    return content.lstrip().startswith(b"%PDF-")


def _validate_upload(file: UploadFile, content: bytes) -> str:
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds UPLOAD_MAX_BYTES")

    filename = Path(file.filename or "upload.pdf").name
    if not filename:
        filename = "upload.pdf"
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Only PDF uploads are supported")

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported content type for upload")
    if not _is_pdf_content(content):
        raise HTTPException(status_code=415, detail="Uploaded content is not a valid PDF")

    return filename


def _validate_idempotency_key(raw_key: str | None) -> str | None:
    if not raw_key:
        return None
    key = raw_key.strip()
    if not key:
        return None
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise HTTPException(
            status_code=422,
            detail="Invalid Idempotency-Key. Use 8-128 chars: letters, numbers, . _ : -",
        )
    return key


def _idempotency_record_path(idempotency_key: str) -> Path:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return IDEMPOTENCY_DIR / f"{digest}.json"


def _request_fingerprint(
    *,
    filename: str,
    content: bytes,
    language: str,
    style: str,
    target_minutes: int,
    target_seconds: int,
    pause_at_script: bool = False,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(filename.encode("utf-8"))
    hasher.update(content)
    hasher.update(language.encode("utf-8"))
    hasher.update(style.encode("utf-8"))
    hasher.update(str(target_minutes).encode("utf-8"))
    hasher.update(str(target_seconds).encode("utf-8"))
    hasher.update(str(pause_at_script).encode("utf-8"))
    return hasher.hexdigest()


def _response_payload(
    job_id: str, request_model: PodcastJobRequest, status: str, *, replayed: bool = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "request": request_model.model_dump(),
    }
    if replayed:
        payload["idempotent_replay"] = True
    return payload


def _require_api_key(request: Request) -> None:
    if not API_KEY:
        return
    header = request.headers.get("x-api-key") or request.headers.get("authorization")
    token = header.replace("Bearer ", "").strip() if header else None
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key")
    if not hmac.compare_digest(token, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _enqueue_job(job_id: str, *, meta: dict | None = None) -> None:
    if QUEUE_MODE == "redis":
        enqueue_redis(QUEUE_REDIS_URL, QUEUE_REDIS_KEY, job_id=job_id, meta=meta)
    elif QUEUE_MODE == "file":
        enqueue_file(QUEUE_FILE, job_id, meta=meta)
    else:
        enqueue_dir(QUEUE_DIR, job_id, meta=meta)


def _queue_depth() -> int:
    if QUEUE_MODE == "redis":
        try:
            import redis  # type: ignore
        except Exception:
            return 0
        client = redis.Redis.from_url(QUEUE_REDIS_URL)
        return int(client.zcard(QUEUE_REDIS_KEY))
    if QUEUE_MODE == "file":
        if not QUEUE_FILE.exists():
            return 0
        lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
        offset_path = QUEUE_FILE.with_suffix(QUEUE_FILE.suffix + ".offset")
        try:
            offset = int(offset_path.read_text(encoding="utf-8"))
        except Exception:
            offset = 0
        return max(0, len(lines) - offset)
    if not QUEUE_DIR.exists():
        return 0
    return len(list(QUEUE_DIR.glob("*.json")))


def _job_status_counts() -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for status_path in JOBS_DIR.glob("*/status.json"):
        data = _read_json(status_path) or {}
        status = data.get("status", "unknown")
        counts[status] += 1
    return dict(counts)


def _stage_metrics() -> dict[str, dict[str, float]]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for metrics_path in PROCESSED_DIR.glob("*/job_metrics.json"):
        data = _read_json(metrics_path)
        if not data:
            continue
        for key, value in data.items():
            if isinstance(value, (int, float)):
                totals[key] += float(value)
                counts[key] += 1
    averages = {k: round(totals[k] / counts[k], 4) for k in totals if counts[k] > 0}
    return {"average_seconds": averages, "samples": dict(counts)}


def _audio_metrics() -> dict[str, Any]:
    total = 0
    with_audio = 0
    for result_path in PROCESSED_DIR.glob("*/result.json"):
        data = _read_json(result_path)
        if not data:
            continue
        total += 1
        artifacts = data.get("artifacts") or []
        has_audio = False
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if artifact.get("kind") == "audio_mp3":
                has_audio = True
                break
            path = artifact.get("path")
            if isinstance(path, str) and path.endswith(".mp3"):
                has_audio = True
                break
        if has_audio:
            with_audio += 1
    rate = (with_audio / total) if total else 0.0
    return {"total_results": total, "with_audio": with_audio, "audio_success_rate": round(rate, 4)}


class FeedbackPayload(BaseModel):
    message: str = Field(..., min_length=4, max_length=4000)
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    job_id: str | None = Field(default=None, max_length=80)
    context: dict[str, Any] | None = None


def _safe_artifact_path(job_id: str, artifact_name: str) -> Path:
    _validate_job_id(job_id)
    job_dir = (PROCESSED_DIR / job_id).resolve()
    candidate = (job_dir / artifact_name).resolve()
    if job_dir in candidate.parents or candidate == job_dir:
        if candidate.exists() and candidate.is_file():
            return candidate
    staging_dir = (Path(os.getenv("STORAGE_STAGING_DIR", "data/staging")) / job_id).resolve()
    staging_candidate = (staging_dir / artifact_name).resolve()
    if (
        (staging_dir in staging_candidate.parents or staging_candidate == staging_dir)
        and staging_candidate.exists()
        and staging_candidate.is_file()
    ):
        return staging_candidate
    raise HTTPException(status_code=404, detail="Artifact not found")


def _job_artifacts(job_id: str) -> list[dict[str, Any]]:
    _validate_job_id(job_id)
    result_path = PROCESSED_DIR / job_id / "result.json"
    result = _read_json(result_path)
    if not result:
        staging_result = (
            Path(os.getenv("STORAGE_STAGING_DIR", "data/staging")) / job_id / "result.json"
        )
        result = _read_json(staging_result)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    artifacts: list[dict[str, Any]] = []
    for artifact in result.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str):
            continue
        name = Path(raw_path).name
        size_bytes: int | None = None
        try:
            path = _safe_artifact_path(job_id, name)
            size_bytes = path.stat().st_size
            local_path = str(path)
        except HTTPException:
            continue
        artifacts.append(
            {
                "name": name,
                "kind": artifact.get("kind"),
                "path": local_path,
                "download_url": f"/v1/jobs/{job_id}/artifacts/{name}",
                "size_bytes": size_bytes,
            }
        )
    return artifacts


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_model=None)
def root() -> Response:
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"status": "ok"})


@app.post("/v1/jobs", dependencies=[Depends(_require_api_key)])
async def create_job(
    request: Request,
    file: UploadFile = UPLOAD_FILE_PARAM,
    language: str = Form("en"),
    style: str = Form("everyday"),
    target_minutes: int = Form(8),
    target_seconds: int = Form(0),
    pause_at_script: bool = Form(False),
    job_id: str | None = Form(None),
) -> JSONResponse:
    content = await file.read()
    filename = _validate_upload(file, content)
    job_id = _validate_job_id(job_id)

    idempotency_key = _validate_idempotency_key(request.headers.get("Idempotency-Key"))
    req_fingerprint = _request_fingerprint(
        filename=filename,
        content=content,
        language=language,
        style=style,
        target_minutes=target_minutes,
        target_seconds=target_seconds,
        pause_at_script=pause_at_script,
    )

    if idempotency_key:
        record = _read_json(_idempotency_record_path(idempotency_key))
        if record:
            if record.get("request_fingerprint") != req_fingerprint:
                raise HTTPException(
                    status_code=409, detail="Idempotency-Key already used with different payload"
                )
            existing_job_id = str(record.get("job_id") or "")
            if existing_job_id:
                status_payload = _read_json(_status_path(existing_job_id))
                request_payload = _read_json(_job_dir(existing_job_id) / "request.json")
                if status_payload and request_payload:
                    req = PodcastJobRequest.model_validate(request_payload)
                    return JSONResponse(
                        _response_payload(
                            existing_job_id,
                            req,
                            str(status_payload.get("status") or JobStatus.QUEUED.value),
                            replayed=True,
                        )
                    )

    if _job_dir(job_id).exists():
        raise HTTPException(status_code=409, detail="Job already exists")

    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_dir / filename
    input_path.write_bytes(content)

    try:
        req = PodcastJobRequest(
            input_filename=filename,
            language=language,
            style=style,
            target_minutes=target_minutes,
            target_seconds=target_seconds,
            pause_at_script=pause_at_script,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    (job_dir / "request.json").write_text(req.model_dump_json(indent=2), encoding="utf-8")

    if idempotency_key:
        record_path = _idempotency_record_path(idempotency_key)
        record_path.write_text(
            json.dumps(
                {
                    "idempotency_key_hash": record_path.stem,
                    "job_id": job_id,
                    "request_fingerprint": req_fingerprint,
                    "created_at": _now_iso(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    _write_status(job_id, status=JobStatus.QUEUED, stage="queued")
    _enqueue_job(job_id, meta={"num_pdfs": 1, "minutes": target_minutes})

    return JSONResponse(_response_payload(job_id, req, JobStatus.QUEUED.value))


@app.get("/v1/jobs/{job_id}/status", dependencies=[Depends(_require_api_key)])
def job_status(job_id: str) -> JSONResponse:
    status = _read_json(_status_path(job_id))
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(status)


@app.get("/v1/jobs/{job_id}/script", dependencies=[Depends(_require_api_key)])
def job_script(job_id: str) -> JSONResponse:
    status = _read_json(_status_path(job_id))
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")

    script_json_path = PROCESSED_DIR / job_id / "script.json"
    if not script_json_path.exists():
        script_json_path = (
            Path(os.getenv("STORAGE_STAGING_DIR", "data/staging")) / job_id / "script.json"
        )
    if not script_json_path.exists():
        raise HTTPException(status_code=404, detail="Script not yet available for this job")

    segments = _read_json(script_json_path) or []
    script_md_path = PROCESSED_DIR / job_id / "script.md"
    if not script_md_path.exists():
        script_md_path = (
            Path(os.getenv("STORAGE_STAGING_DIR", "data/staging")) / job_id / "script.md"
        )
    script_md = script_md_path.read_text(encoding="utf-8") if script_md_path.exists() else ""

    return JSONResponse(
        {
            "job_id": job_id,
            "status": status.get("status"),
            "segments": segments,
            "script_md": script_md,
        }
    )


@app.post("/v1/jobs/{job_id}/review", dependencies=[Depends(_require_api_key)])
def job_review(job_id: str, review: ScriptReviewRequest) -> JSONResponse:
    status = _read_json(_status_path(job_id))
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")

    current_status = status.get("status")
    if current_status != JobStatus.AWAITING_REVIEW.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is in state '{current_status}', must be '{JobStatus.AWAITING_REVIEW.value}' to review.",
        )

    job_dir = _job_dir(job_id)
    review_record: dict[str, Any] = {
        "job_id": job_id,
        "action": review.action.value,
        "notes": review.notes,
        "reviewed_at": _now_iso(),
    }

    if review.action == ScriptReviewAction.REJECT:
        (job_dir / "review.json").write_text(json.dumps(review_record, indent=2), encoding="utf-8")
        _write_status(
            job_id,
            status=JobStatus.FAILED,
            stage="rejected",
            detail=review.notes or "Script rejected by reviewer",
        )
        return JSONResponse(
            ScriptReviewResponse(
                job_id=job_id,
                status=JobStatus.FAILED,
                message="Script rejected. Job marked as failed.",
            ).model_dump()
        )

    # Action is APPROVE
    if review.segments is not None:
        review_record["segments"] = [s.model_dump() for s in review.segments]
        script_json_path = PROCESSED_DIR / job_id / "script.json"
        script_json_path.parent.mkdir(parents=True, exist_ok=True)
        script_json_path.write_text(
            json.dumps(review_record["segments"], indent=2), encoding="utf-8"
        )
        lines = ["# Podcast Script", ""]
        for s in review.segments:
            lines.append(f"## {s.title}")
            lines.append(f"**{s.speaker}:** {s.text}")
            lines.append("")
        (PROCESSED_DIR / job_id / "script.md").write_text("\n".join(lines), encoding="utf-8")

    (job_dir / "review.json").write_text(json.dumps(review_record, indent=2), encoding="utf-8")
    _write_status(
        job_id,
        status=JobStatus.QUEUED,
        stage="reviewed",
        detail="Script approved by reviewer. Queued for audio synthesis.",
    )
    _enqueue_job(job_id, meta={"resumed": True, "reviewed": True})

    return JSONResponse(
        ScriptReviewResponse(
            job_id=job_id,
            status=JobStatus.QUEUED,
            message="Script approved. Queued for audio synthesis.",
        ).model_dump()
    )


@app.get("/v1/jobs/{job_id}/result", dependencies=[Depends(_require_api_key)])
def job_result(job_id: str) -> JSONResponse:
    _validate_job_id(job_id)
    result_path = PROCESSED_DIR / job_id / "result.json"
    result = _read_json(result_path)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return JSONResponse(result)


@app.get("/v1/jobs/{job_id}/artifacts", dependencies=[Depends(_require_api_key)])
def job_artifacts(job_id: str) -> JSONResponse:
    artifacts = _job_artifacts(job_id)
    return JSONResponse({"job_id": job_id, "artifacts": artifacts})


@app.get("/v1/jobs/{job_id}/artifacts/{artifact_name}", dependencies=[Depends(_require_api_key)])
def job_artifact_download(job_id: str, artifact_name: str) -> Response:
    _validate_job_id(job_id)
    store = create_job_store(base_dir=PROCESSED_DIR)
    presigned = store.get_download_url(job_id=job_id, name=artifact_name)
    if presigned:
        return RedirectResponse(url=presigned, status_code=307)
    path = _safe_artifact_path(job_id, artifact_name)
    return FileResponse(path, filename=artifact_name)


@app.get("/v1/jobs/{job_id}/progress", dependencies=[Depends(_require_api_key)])
async def job_progress(job_id: str) -> StreamingResponse:
    async def event_stream():
        last_payload = None
        while True:
            status = _read_json(_status_path(job_id))
            if not status:
                payload = json.dumps({"error": "Job not found"})
                yield f"event: error\ndata: {payload}\n\n"
                break
            payload = json.dumps(status)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if status.get("status") in {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value}:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/v1/metrics/summary", dependencies=[Depends(_require_api_key)])
def metrics_summary() -> JSONResponse:
    payload = {
        "queue_mode": QUEUE_MODE,
        "queue_depth": _queue_depth(),
        "job_counts": _job_status_counts(),
        "stage_metrics": _stage_metrics(),
        "audio_metrics": _audio_metrics(),
        "generated_at": _now_iso(),
    }
    return JSONResponse(payload)


@app.post("/v1/feedback", dependencies=[Depends(_require_api_key)])
def submit_feedback(payload: FeedbackPayload, request: Request) -> JSONResponse:
    feedback_id = f"feedback-{uuid.uuid4().hex[:8]}"
    record = {
        "feedback_id": feedback_id,
        "message": payload.message,
        "name": payload.name,
        "email": payload.email,
        "job_id": payload.job_id,
        "context": payload.context,
        "user_agent": request.headers.get("user-agent"),
        "received_at": _now_iso(),
    }
    path = FEEDBACK_DIR / f"{feedback_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return JSONResponse({"feedback_id": feedback_id, "status": "received"})
