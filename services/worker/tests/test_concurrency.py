from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from podcastify_worker import main as worker_main


@pytest.fixture()
def worker_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    jobs_dir = data_dir / "jobs"
    processed_dir = data_dir / "processed"
    dead_letter_dir = data_dir / "dead_letter"
    queue_dir = data_dir / "queue"
    queue_file = queue_dir / "queue.jsonl"

    monkeypatch.setattr(worker_main, "DATA_DIR", data_dir)
    monkeypatch.setattr(worker_main, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(worker_main, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(worker_main, "DEAD_LETTER_DIR", dead_letter_dir)
    monkeypatch.setattr(worker_main, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(worker_main, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(worker_main, "QUEUE_MODE", "dir")
    monkeypatch.setattr(worker_main, "WORKER_MAX_CONCURRENT", 2)
    monkeypatch.setattr(worker_main, "JOB_CLAIM_STALE_S", 1.0)
    worker_main._ensure_data_dirs()

    return {
        "jobs_dir": jobs_dir,
        "queue_dir": queue_dir,
    }


def test_dispatch_jobs_respects_max_concurrent(
    worker_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = iter(["job-1", "job-2", "job-3", None])
    monkeypatch.setattr(worker_main, "_next_job", lambda: next(jobs))
    monkeypatch.setattr(worker_main, "_process_job", lambda job_id: None)

    with ThreadPoolExecutor(max_workers=4) as executor:
        inflight = {}
        scheduled = worker_main._dispatch_jobs(executor, inflight)

    assert scheduled == 2
    assert len(inflight) == 2


def test_claim_job_reuses_stale_lock(
    worker_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = "job-stale-lock"
    claim_path = worker_main._claim_path(job_id)
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim_path.write_text("stale", encoding="utf-8")
    old = time.time() - 120
    monkeypatch.setattr(worker_main, "JOB_CLAIM_STALE_S", 1.0)
    claim_path.touch()
    claim_path.chmod(0o644)
    # Make the claim older than stale threshold.
    os.utime(claim_path, (old, old))

    assert worker_main._claim_job(job_id) is True
    worker_main._release_job_claim(job_id)


def test_process_job_skips_when_claimed(
    worker_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = "job-claimed"
    invoked = {"called": False}
    assert worker_main._claim_job(job_id) is True

    def should_not_run(_job_id: str) -> str:
        invoked["called"] = True
        return ""

    monkeypatch.setattr(worker_main, "_execute_job", should_not_run)
    worker_main._process_job(job_id)

    assert invoked["called"] is False
    assert not worker_main._attempt_path(job_id).exists()
    worker_main._release_job_claim(job_id)
