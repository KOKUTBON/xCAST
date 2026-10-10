"""HTTP Client SDK for interacting with the Thinking in Code API."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
from podcastify_contracts.podcast_job import (
    EpisodeSegment,
    JobStatus,
    ScriptReviewAction,
    ScriptReviewRequest,
    ScriptReviewResponse,
)


class ClientError(Exception):
    """Raised when an API call fails."""

    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class JobTimeoutError(ClientError):
    """Raised when waiting for a job exceeds the timeout."""


class ThinkingInCodeClient:
    """Client for Thinking in Code / Podcastify REST and SSE endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("TIC_API_URL")
            or os.getenv("PODCASTIFY_API_URL")
            or "http://localhost:8000"
        ).rstrip("/")
        self.api_key = api_key or os.getenv("TIC_API_KEY") or os.getenv("PODCASTIFY_API_KEY")
        self.timeout = timeout
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=self.timeout)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> ThinkingInCodeClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _handle_response(self, response: httpx.Response) -> Any:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                body = response.json()
                detail = body.get("detail", response.text)
            except Exception:
                detail = response.text
            raise ClientError(
                f"HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc
        return response.json() if response.content else None

    def health(self) -> dict[str, Any]:
        """Check the health status of the API server."""
        resp = self._client.get("/health")
        return self._handle_response(resp)

    def submit_job(
        self,
        pdf_path: str | Path,
        *,
        language: str = "en",
        style: str = "everyday",
        target_minutes: int = 8,
        target_seconds: int = 0,
        pause_at_script: bool = False,
        job_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Submit a PDF document to generate a podcast episode."""
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF file not found: {path}")

        files = {"file": (path.name, path.open("rb"), "application/pdf")}
        data: dict[str, Any] = {
            "language": language,
            "style": style,
            "target_minutes": str(target_minutes),
            "target_seconds": str(target_seconds),
            "pause_at_script": "true" if pause_at_script else "false",
        }
        if job_id:
            data["job_id"] = job_id

        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        try:
            resp = self._client.post("/v1/jobs", files=files, data=data, headers=headers)
        finally:
            files["file"][1].close()

        return self._handle_response(resp)

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Get the current execution status and stage for a job."""
        resp = self._client.get(f"/v1/jobs/{job_id}/status")
        return self._handle_response(resp)

    def get_result(self, job_id: str) -> dict[str, Any]:
        """Get the final result metadata of a completed job."""
        resp = self._client.get(f"/v1/jobs/{job_id}/result")
        return self._handle_response(resp)

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        """List generated artifacts for a job."""
        resp = self._client.get(f"/v1/jobs/{job_id}/artifacts")
        data = self._handle_response(resp)
        return data.get("artifacts", [])

    def get_script(self, job_id: str) -> dict[str, Any]:
        """Fetch the generated script segments and markdown for review."""
        resp = self._client.get(f"/v1/jobs/{job_id}/script")
        return self._handle_response(resp)

    def submit_review(
        self,
        job_id: str,
        action: ScriptReviewAction | str,
        *,
        segments: list[EpisodeSegment | dict[str, Any]] | None = None,
        notes: str | None = None,
    ) -> ScriptReviewResponse:
        """Submit an approval or rejection for a paused script."""
        action_val = action.value if isinstance(action, ScriptReviewAction) else str(action)
        review_req = ScriptReviewRequest(
            action=ScriptReviewAction(action_val),
            notes=notes,
            segments=segments,
        )
        resp = self._client.post(
            f"/v1/jobs/{job_id}/review",
            json=review_req.model_dump(),
        )
        data = self._handle_response(resp)
        return ScriptReviewResponse.model_validate(data)

    def stream_progress(self, job_id: str) -> Generator[dict[str, Any], None, None]:
        """Stream progress updates via Server-Sent Events (SSE)."""
        url = f"{self.base_url}/v1/jobs/{job_id}/progress"
        headers = dict(self._client.headers)
        headers["Accept"] = "text/event-stream"

        with httpx.stream(
            "GET", url, headers=headers, timeout=None, follow_redirects=True
        ) as response:
            if response.status_code != 200:
                body = response.read().decode("utf-8", errors="replace")
                raise ClientError(
                    f"HTTP {response.status_code}: {body}",
                    status_code=response.status_code,
                    response_body=body,
                )

            for line in response.iter_lines():
                if not line:
                    continue
                line = line.strip()
                if line.startswith("data:"):
                    payload_str = line[len("data:") :].strip()
                    if payload_str:
                        try:
                            payload = json.loads(payload_str)
                            yield payload
                        except json.JSONDecodeError:
                            continue

    def wait_for_completion(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 300.0,
        poll_interval: float = 2.0,
        stop_on_review: bool = True,
    ) -> dict[str, Any]:
        """Poll job status until terminal state or awaiting review."""
        start_time = time.monotonic()
        while True:
            status_data = self.get_status(job_id)
            current_status = status_data.get("status")

            if current_status in {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value}:
                return status_data

            if stop_on_review and current_status == JobStatus.AWAITING_REVIEW.value:
                return status_data

            if time.monotonic() - start_time > timeout_seconds:
                raise JobTimeoutError(
                    f"Job {job_id} did not finish within {timeout_seconds} seconds (status: {current_status})"
                )

            time.sleep(poll_interval)

    def download_artifact(
        self,
        job_id: str,
        artifact_name: str,
        output_path: str | Path,
    ) -> Path:
        """Download a specific artifact file to local disk."""
        target = Path(output_path)
        if target.is_dir():
            target = target / artifact_name
        target.parent.mkdir(parents=True, exist_ok=True)

        resp = self._client.get(
            f"/v1/jobs/{job_id}/artifacts/{artifact_name}",
            follow_redirects=True,
        )
        if resp.status_code != 200:
            raise ClientError(
                f"Failed to download artifact '{artifact_name}': HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        target.write_bytes(resp.content)
        return target
