from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from podcastify_api import main as api_main

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data_dir = tmp_path / "data"
    jobs_dir = data_dir / "jobs"
    processed_dir = data_dir / "processed"
    feedback_dir = data_dir / "feedback"
    idempotency_dir = data_dir / "idempotency"
    queue_dir = data_dir / "queue"
    queue_file = queue_dir / "queue.jsonl"

    monkeypatch.setattr(api_main, "DATA_DIR", data_dir)
    monkeypatch.setattr(api_main, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(api_main, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(api_main, "FEEDBACK_DIR", feedback_dir)
    monkeypatch.setattr(api_main, "IDEMPOTENCY_DIR", idempotency_dir)
    monkeypatch.setattr(api_main, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(api_main, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(api_main, "QUEUE_MODE", "dir")
    monkeypatch.setattr(api_main, "MAX_UPLOAD_BYTES", 1024 * 1024)
    monkeypatch.setattr(api_main, "API_KEY", "")
    api_main._ensure_data_dirs()

    return TestClient(api_main.app)


def _submit_job(
    client: TestClient,
    *,
    filename: str = "paper.pdf",
    payload: bytes = PDF_BYTES,
    content_type: str = "application/pdf",
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
):
    return client.post(
        "/v1/jobs",
        files={"file": (filename, payload, content_type)},
        data=data or {},
        headers=headers or {},
    )


def test_create_job_rejects_invalid_job_id(client: TestClient) -> None:
    response = _submit_job(client, data={"job_id": "../escape"})
    assert response.status_code == 422
    assert "Invalid job_id" in response.text


def test_create_job_rejects_non_pdf_content(client: TestClient) -> None:
    response = _submit_job(client, payload=b"hello world")
    assert response.status_code == 415
    assert "valid PDF" in response.text


def test_create_job_rejects_oversized_upload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_main, "MAX_UPLOAD_BYTES", 16)
    response = _submit_job(client, payload=b"%PDF-1.7 " + b"x" * 128)
    assert response.status_code == 413


def test_create_job_supports_idempotent_replay(client: TestClient) -> None:
    headers = {"Idempotency-Key": "upload-job-12345678"}
    first = _submit_job(client, headers=headers)
    assert first.status_code == 200
    job_id = first.json()["job_id"]

    second = _submit_job(client, headers=headers)
    assert second.status_code == 200
    payload = second.json()
    assert payload["job_id"] == job_id
    assert payload.get("idempotent_replay") is True

    queued_items = list(api_main.QUEUE_DIR.glob("*.json"))
    assert len(queued_items) == 1


def test_create_job_rejects_idempotency_key_payload_conflict(client: TestClient) -> None:
    headers = {"Idempotency-Key": "upload-job-abcdefgh"}
    first = _submit_job(client, headers=headers, data={"style": "everyday"})
    assert first.status_code == 200

    second = _submit_job(client, headers=headers, data={"style": "technical"})
    assert second.status_code == 409


def test_create_job_rejects_invalid_idempotency_key(client: TestClient) -> None:
    headers = {"Idempotency-Key": "bad key"}
    response = _submit_job(client, headers=headers)
    assert response.status_code == 422
    assert "Invalid Idempotency-Key" in response.text


def test_create_job_rejects_duplicate_job_id(client: TestClient) -> None:
    first = _submit_job(client, data={"job_id": "job-duplicate-1"})
    assert first.status_code == 200

    second = _submit_job(client, data={"job_id": "job-duplicate-1"})
    assert second.status_code == 409
