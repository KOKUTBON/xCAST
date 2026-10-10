from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from podcastify_podcast.application.ports import JobStore


class FileSystemJobStore(JobStore):
    def __init__(self, base_dir: str = "data/processed") -> None:
        self.base_dir = Path(base_dir)
        self.write_retries = int(os.getenv("ARTIFACT_WRITE_RETRIES", "3"))
        self.write_backoff_s = float(os.getenv("ARTIFACT_WRITE_BACKOFF_S", "0.2"))

    def job_dir(self, job_id: str) -> Path:
        d = self.base_dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_artifact(self, *, job_id: str, name: str, content: bytes) -> str:
        path = self.job_dir(job_id) / name
        self._write_bytes_with_retry(path, content)
        return str(path)

    def read_artifact(self, *, job_id: str, name: str) -> bytes:
        path = self.job_dir(job_id) / name
        if not path.exists():
            raise FileNotFoundError(f"Artifact {name} not found for job {job_id}")
        return path.read_bytes()

    def artifact_exists(self, *, job_id: str, name: str) -> bool:
        path = self.job_dir(job_id) / name
        return path.exists() and path.is_file()

    def list_artifacts(self, *, job_id: str) -> list[str]:
        d = self.job_dir(job_id)
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_file())

    def delete_job_data(self, *, job_id: str) -> None:
        d = self.base_dir / job_id
        if d.exists() and d.is_dir():
            shutil.rmtree(d, ignore_errors=True)

    def get_download_url(self, *, job_id: str, name: str, expires_in: int = 3600) -> str | None:
        return None

    def _write_bytes_with_retry(self, path: Path, content: bytes) -> None:
        last_exc: Exception | None = None
        for attempt in range(max(1, self.write_retries)):
            try:
                path.write_bytes(content)
                return
            except Exception as exc:  # pragma: no cover - defensive
                last_exc = exc
                time.sleep(self.write_backoff_s * (2**attempt))
        if last_exc:
            raise last_exc
