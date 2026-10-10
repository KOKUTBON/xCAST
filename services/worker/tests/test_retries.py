from __future__ import annotations

import json
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
    monkeypatch.setattr(worker_main, "MAX_JOB_ATTEMPTS", 3)
    monkeypatch.setattr(worker_main, "RETRY_BACKOFF_S", 0.0)
    worker_main._ensure_data_dirs()

    return {
        "data_dir": data_dir,
        "jobs_dir": jobs_dir,
        "processed_dir": processed_dir,
        "dead_letter_dir": dead_letter_dir,
        "queue_dir": queue_dir,
    }


def test_process_job_requeues_before_max_attempts(
    worker_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    enqueued: list[tuple[str, dict | None]] = []

    def fail_once(job_id: str) -> str:
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(worker_main, "_execute_job", fail_once)
    monkeypatch.setattr(
        worker_main, "_enqueue_job", lambda job_id, meta=None: enqueued.append((job_id, meta))
    )
    monkeypatch.setattr(worker_main, "MAX_JOB_ATTEMPTS", 2)

    worker_main._process_job("job-retry")

    assert len(enqueued) == 1
    assert enqueued[0][0] == "job-retry"
    status_path = worker_main.JOBS_DIR / "job-retry" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "queued"
    assert status["stage"] == "retrying"
    assert not list(worker_main.DEAD_LETTER_DIR.glob("*.json"))


def test_process_job_writes_dead_letter_after_last_attempt(
    worker_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_main, "MAX_JOB_ATTEMPTS", 1)
    monkeypatch.setattr(worker_main, "_enqueue_job", lambda job_id, meta=None: None)

    def always_fail(job_id: str) -> str:
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(worker_main, "_execute_job", always_fail)

    worker_main._process_job("job-dead-letter")

    status_path = worker_main.JOBS_DIR / "job-dead-letter" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["stage"] == "error"
    dead_letters = list(worker_main.DEAD_LETTER_DIR.glob("job-dead-letter-*.json"))
    assert len(dead_letters) == 1
    payload = json.loads(dead_letters[0].read_text(encoding="utf-8"))
    assert payload["attempt"] == 1
    assert payload["max_attempts"] == 1


def test_process_job_clears_attempt_state_on_success(
    worker_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        worker_main,
        "_execute_job",
        lambda job_id: (
            str(worker_main.PROCESSED_DIR / job_id / "result.json"),
            worker_main.JobStatus.SUCCEEDED,
        ),
    )

    worker_main._increment_attempt("job-success")
    attempt_path = worker_main._attempt_path("job-success")
    assert attempt_path.exists()

    worker_main._process_job("job-success")

    assert not attempt_path.exists()
    status_path = worker_main.JOBS_DIR / "job-success" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "succeeded"
    assert status["stage"] == "done"


def test_process_job_pauses_for_review(
    worker_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        worker_main,
        "_execute_job",
        lambda job_id: (
            str(worker_main.PROCESSED_DIR / job_id / "result.json"),
            worker_main.JobStatus.AWAITING_REVIEW,
        ),
    )

    worker_main._process_job("job-review")

    status_path = worker_main.JOBS_DIR / "job-review" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "awaiting_review"
    assert status["stage"] == "awaiting_review"
