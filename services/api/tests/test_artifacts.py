from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from podcastify_api import main as api_main


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(api_main, "DATA_DIR", data_dir)
    monkeypatch.setattr(api_main, "JOBS_DIR", data_dir / "jobs")
    monkeypatch.setattr(api_main, "PROCESSED_DIR", data_dir / "processed")
    monkeypatch.setattr(api_main, "FEEDBACK_DIR", data_dir / "feedback")
    monkeypatch.setattr(api_main, "IDEMPOTENCY_DIR", data_dir / "idempotency")
    monkeypatch.setattr(api_main, "QUEUE_DIR", data_dir / "queue")
    monkeypatch.setattr(api_main, "QUEUE_FILE", data_dir / "queue" / "queue.jsonl")
    monkeypatch.setattr(api_main, "API_KEY", "")
    api_main._ensure_data_dirs()
    return TestClient(api_main.app)


def test_artifacts_endpoint_filters_missing_or_unsafe_paths(client: TestClient) -> None:
    job_id = "job-artifacts"
    out_dir = api_main.PROCESSED_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = out_dir / "script.md"
    script_path.write_text("# Script", encoding="utf-8")
    result_payload = {
        "artifacts": [
            {"kind": "script_markdown", "path": str(script_path)},
            {"kind": "unsafe", "path": "/tmp/escape.txt"},
            {"kind": "missing", "path": str(out_dir / "nope.txt")},
        ]
    }
    (out_dir / "result.json").write_text(json.dumps(result_payload), encoding="utf-8")

    res = client.get(f"/v1/jobs/{job_id}/artifacts")
    assert res.status_code == 200
    artifacts = res.json()["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["name"] == "script.md"
    assert artifacts[0]["download_url"] == f"/v1/jobs/{job_id}/artifacts/script.md"


def test_artifact_download_endpoint(client: TestClient) -> None:
    job_id = "job-download"
    out_dir = api_main.PROCESSED_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / "script.md"
    file_path.write_text("content", encoding="utf-8")

    res = client.get(f"/v1/jobs/{job_id}/artifacts/script.md")
    assert res.status_code == 200
    assert "content" in res.text


def test_artifact_download_rejects_unknown_file(client: TestClient) -> None:
    res = client.get("/v1/jobs/job-unknown/artifacts/missing.txt")
    assert res.status_code == 404


def test_api_key_is_not_accepted_in_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_main, "API_KEY", "test-key")
    url = "/v1/jobs/job-download/status?api_key=test-key"
    assert client.get(url).status_code == 401
    assert (
        client.get("/v1/jobs/job-download/status", headers={"x-api-key": "test-key"}).status_code
        != 401
    )


def test_artifact_helpers_reject_invalid_job_id(client: TestClient) -> None:
    with pytest.raises(HTTPException) as exc:
        api_main._job_artifacts("..")
    assert exc.value.status_code == 422
