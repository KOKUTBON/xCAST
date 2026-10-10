from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from podcastify_contracts.podcast_job import (
    EpisodeSegment,
    JobStatus,
    PodcastJobRequest,
    ScriptReviewAction,
    ScriptReviewRequest,
    ScriptReviewResponse,
)
from podcastify_podcast.application.use_cases import GeneratePodcastFromPdf
from podcastify_podcast.domain.models import Chunk, PageText
from podcastify_podcast.infrastructure.storage.fs_store import FileSystemJobStore


def test_review_contract_models():
    req = ScriptReviewRequest(action=ScriptReviewAction.APPROVE)
    assert req.action == "approve"
    assert req.segments is None

    resp = ScriptReviewResponse(job_id="job-1", status=JobStatus.AWAITING_REVIEW, message="Waiting")
    assert resp.status == "awaiting_review"

    job_req = PodcastJobRequest(input_filename="doc.pdf", pause_at_script=True)
    assert job_req.pause_at_script is True


def test_pipeline_pauses_at_script(tmp_path: Path):
    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = [PageText(page_number=1, text="Sample text")]

    mock_chunker = MagicMock()
    mock_chunker.chunk.return_value = [Chunk(text="Chunk 1")]

    mock_writer = MagicMock()
    mock_writer.write_script.return_value = [
        EpisodeSegment(title="Intro", speaker="Host", text="Hello world.")
    ]

    mock_tts = MagicMock()
    mock_audio = MagicMock()
    job_store = FileSystemJobStore(base_dir=str(tmp_path))

    pipeline = GeneratePodcastFromPdf(
        pdf_extractor=mock_extractor,
        chunker=mock_chunker,
        script_writer=mock_writer,
        job_store=job_store,
        tts=mock_tts,
        audio=mock_audio,
    )

    request = PodcastJobRequest(
        input_filename="paper.pdf",
        pause_at_script=True,
    )

    result = pipeline.run(job_id="job-pause-test", request=request, pdf_bytes=b"%PDF-test")

    assert result.status == JobStatus.AWAITING_REVIEW
    assert len(result.segments) == 1
    assert result.segments[0].title == "Intro"

    # TTS and audio must not be invoked during script pause
    mock_tts.synthesize.assert_not_called()
    mock_audio.assemble.assert_not_called()

    # Script artifacts must be saved
    assert job_store.artifact_exists(job_id="job-pause-test", name="script.md")
    assert job_store.artifact_exists(job_id="job-pause-test", name="script.json")
    assert job_store.artifact_exists(job_id="job-pause-test", name="transcript.txt")

    # script.json should contain the serialized segment
    script_data = json.loads(
        job_store.read_artifact(job_id="job-pause-test", name="script.json").decode("utf-8")
    )
    assert len(script_data) == 1
    assert script_data[0]["title"] == "Intro"


def test_pipeline_resumes_with_pre_approved_segments(tmp_path: Path):
    mock_extractor = MagicMock()
    mock_chunker = MagicMock()
    mock_writer = MagicMock()

    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = ["/tmp/seg1.wav"]

    mock_audio = MagicMock()
    mock_audio.assemble.return_value = str(tmp_path / "job-resume-test" / "episode.mp3")

    job_store = FileSystemJobStore(base_dir=str(tmp_path))

    pipeline = GeneratePodcastFromPdf(
        pdf_extractor=mock_extractor,
        chunker=mock_chunker,
        script_writer=mock_writer,
        job_store=job_store,
        tts=mock_tts,
        audio=mock_audio,
    )

    request = PodcastJobRequest(
        input_filename="paper.pdf",
        pause_at_script=True,
    )

    approved_segments = [
        EpisodeSegment(title="Custom Title", speaker="Alex", text="Approved narration content.")
    ]

    result = pipeline.run(
        job_id="job-resume-test",
        request=request,
        pdf_bytes=b"",
        pre_approved_segments=approved_segments,
    )

    assert result.status == JobStatus.SUCCEEDED
    assert result.title == "Custom Title"

    # Extraction and script writing should be skipped
    mock_extractor.extract.assert_not_called()
    mock_chunker.chunk.assert_not_called()
    mock_writer.write_script.assert_not_called()

    # Audio synthesis must be invoked
    mock_tts.synthesize.assert_called_once()
    mock_audio.assemble.assert_called_once()
