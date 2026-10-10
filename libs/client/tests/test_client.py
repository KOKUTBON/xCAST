from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from podcastify_client.cli import main as cli_main
from podcastify_client.client import ClientError, JobTimeoutError, ThinkingInCodeClient
from podcastify_contracts.podcast_job import (
    EpisodeSegment,
    JobStatus,
    ScriptReviewAction,
)


def test_client_init_and_close(monkeypatch):
    monkeypatch.setenv("TIC_API_URL", "http://testserver:9000")
    monkeypatch.setenv("TIC_API_KEY", "secret-test-key")
    with ThinkingInCodeClient() as client:
        assert client.base_url == "http://testserver:9000"
        assert client.api_key == "secret-test-key"
        assert client._client.headers.get("X-API-Key") == "secret-test-key"


def test_client_health():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    assert client.health() == {"status": "ok"}


def test_client_submit_job(tmp_path: Path):
    dummy_pdf = tmp_path / "paper.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 mock content")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/jobs"
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "job_id": "job-12345",
                "status": "queued",
                "request": {"language": "en", "style": "everyday"},
            },
        )

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    res = client.submit_job(
        dummy_pdf,
        language="en",
        style="everyday",
        target_minutes=5,
        pause_at_script=True,
        job_id="job-12345",
        idempotency_key="idem-key-123",
    )
    assert res["job_id"] == "job-12345"
    assert res["status"] == "queued"


def test_client_get_status_and_result():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/jobs/job-123/status":
            return httpx.Response(
                200, json={"job_id": "job-123", "status": "running", "stage": "synthesizing"}
            )
        if request.url.path == "/v1/jobs/job-123/result":
            return httpx.Response(
                200, json={"job_id": "job-123", "artifacts": [{"name": "podcast.mp3"}]}
            )
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    status = client.get_status("job-123")
    assert status["status"] == "running"

    result = client.get_result("job-123")
    assert len(result["artifacts"]) == 1


def test_client_get_script_and_review():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/jobs/job-rev/script":
            return httpx.Response(
                200,
                json={
                    "job_id": "job-rev",
                    "status": "awaiting_review",
                    "segments": [{"speaker": "Host", "text": "Hello world", "title": "Intro"}],
                    "script_md": "# Script\nHello world",
                },
            )
        if request.url.path == "/v1/jobs/job-rev/review":
            data = json.loads(request.content)
            assert data["action"] == "approve"
            return httpx.Response(
                200,
                json={
                    "job_id": "job-rev",
                    "status": "queued",
                    "message": "Script approved.",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    script_data = client.get_script("job-rev")
    assert len(script_data["segments"]) == 1

    review_res = client.submit_review(
        "job-rev",
        action=ScriptReviewAction.APPROVE,
        segments=[EpisodeSegment(speaker="Host", text="Modified hello", title="Intro")],
        notes="Looks great!",
    )
    assert review_res.status == JobStatus.QUEUED
    assert review_res.message == "Script approved."


def test_client_download_artifact(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/jobs/job-123/artifacts/podcast.mp3":
            return httpx.Response(200, content=b"FAKE-MP3-BINARY-DATA")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    out_file = tmp_path / "downloaded.mp3"
    saved = client.download_artifact("job-123", "podcast.mp3", out_file)
    assert saved == out_file
    assert out_file.read_bytes() == b"FAKE-MP3-BINARY-DATA"


def test_client_error_handling():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Job not found"})

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    with pytest.raises(ClientError) as exc_info:
        client.get_status("missing-job")
    assert exc_info.value.status_code == 404
    assert "Job not found" in str(exc_info.value)


def test_client_wait_for_completion_stop_on_review():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job-rev", "status": "awaiting_review"})

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    status = client.wait_for_completion("job-rev", stop_on_review=True, timeout_seconds=5)
    assert status["status"] == "awaiting_review"


def test_client_wait_for_completion_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "job-running", "status": "running"})

    transport = httpx.MockTransport(handler)
    client = ThinkingInCodeClient(base_url="http://testserver")
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    with pytest.raises(JobTimeoutError):
        client.wait_for_completion("job-running", timeout_seconds=0.1, poll_interval=0.05)


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Thinking in Code (Podcastify) CLI client" in captured.out


def test_cli_status(monkeypatch, capsys):
    def fake_status(self, job_id):
        return {"job_id": job_id, "status": "running", "stage": "extracting"}

    monkeypatch.setattr(ThinkingInCodeClient, "get_status", fake_status)
    code = cli_main(["status", "job-999"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Job ID: job-999" in captured.out
    assert "Status: running" in captured.out
    assert "Stage : extracting" in captured.out


def test_cli_status_json(monkeypatch, capsys):
    def fake_status(self, job_id):
        return {"job_id": job_id, "status": "succeeded"}

    monkeypatch.setattr(ThinkingInCodeClient, "get_status", fake_status)
    code = cli_main(["status", "job-999", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["job_id"] == "job-999"
    assert data["status"] == "succeeded"


def test_cli_submit_nonexistent(capsys):
    code = cli_main(["submit", "/nonexistent/path/doc.pdf"])
    assert code == 1
    captured = capsys.readouterr()
    assert "file not found" in captured.err


def test_cli_review(monkeypatch, capsys):
    from podcastify_contracts.podcast_job import ScriptReviewResponse

    def fake_review(self, job_id, action, segments=None, notes=None):
        return ScriptReviewResponse(
            job_id=job_id,
            status=JobStatus.QUEUED,
            message="Script approved.",
        )

    monkeypatch.setattr(ThinkingInCodeClient, "submit_review", fake_review)
    code = cli_main(["review", "job-rev", "approve", "--notes", "LGTM"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Review submitted successfully" in captured.out
    assert "Status : queued" in captured.out
