from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from podcastify_podcast.infrastructure.storage.factory import create_job_store
from podcastify_podcast.infrastructure.storage.fs_store import FileSystemJobStore
from podcastify_podcast.infrastructure.storage.s3_store import S3JobStore


def test_fs_job_store_lifecycle(tmp_path: Path):
    store = FileSystemJobStore(base_dir=str(tmp_path))
    job_id = "job-test-fs"

    assert not store.artifact_exists(job_id=job_id, name="script.md")
    assert store.list_artifacts(job_id=job_id) == []

    # Write artifact
    content = b"# Test Script"
    path_str = store.write_artifact(job_id=job_id, name="script.md", content=content)
    assert Path(path_str).exists()
    assert store.artifact_exists(job_id=job_id, name="script.md")

    # Read artifact
    assert store.read_artifact(job_id=job_id, name="script.md") == content

    # Non-existent artifact raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        store.read_artifact(job_id=job_id, name="missing.txt")

    # Write second artifact
    store.write_artifact(job_id=job_id, name="audio.mp3", content=b"fake-audio")
    artifacts = store.list_artifacts(job_id=job_id)
    assert artifacts == ["audio.mp3", "script.md"]

    # Presigned URL is None for local store
    assert store.get_download_url(job_id=job_id, name="script.md") is None

    # Delete job data
    store.delete_job_data(job_id=job_id)
    assert not store.artifact_exists(job_id=job_id, name="script.md")
    assert store.list_artifacts(job_id=job_id) == []


def test_s3_job_store_lifecycle(tmp_path: Path):
    mock_s3 = MagicMock()
    staging_dir = tmp_path / "staging"
    store = S3JobStore(
        bucket="test-bucket",
        prefix="podcasts",
        staging_dir=str(staging_dir),
        client=mock_s3,
    )
    job_id = "job-test-s3"

    # Write artifact
    content = b"# S3 Script"
    uri = store.write_artifact(job_id=job_id, name="script.md", content=content)
    assert uri == "s3://test-bucket/podcasts/job-test-s3/script.md"
    mock_s3.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="podcasts/job-test-s3/script.md",
        Body=content,
        ContentType="text/markdown",
    )
    # Staged locally as well
    staged = staging_dir / job_id / "script.md"
    assert staged.exists()
    assert staged.read_bytes() == content

    # Read artifact
    mock_body = MagicMock()
    mock_body.read.return_value = content
    mock_s3.get_object.return_value = {"Body": mock_body}

    read_bytes = store.read_artifact(job_id=job_id, name="script.md")
    assert read_bytes == content
    mock_s3.get_object.assert_called_with(
        Bucket="test-bucket", Key="podcasts/job-test-s3/script.md"
    )

    # Read missing artifact
    mock_s3.get_object.side_effect = Exception("NoSuchKey: The specified key does not exist.")
    with pytest.raises(FileNotFoundError):
        store.read_artifact(job_id=job_id, name="notfound.md")
    mock_s3.get_object.side_effect = None

    # Exists check
    mock_s3.head_object.return_value = {}
    assert store.artifact_exists(job_id=job_id, name="script.md")
    mock_s3.head_object.side_effect = Exception("404")
    assert not store.artifact_exists(job_id=job_id, name="missing.md")
    mock_s3.head_object.side_effect = None

    # List artifacts
    mock_s3.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "podcasts/job-test-s3/episode.mp3"},
            {"Key": "podcasts/job-test-s3/script.md"},
        ]
    }
    assert store.list_artifacts(job_id=job_id) == ["episode.mp3", "script.md"]

    # Presigned URL
    mock_s3.generate_presigned_url.return_value = "https://s3.amazonaws.com/test-bucket/signed"
    url = store.get_download_url(job_id=job_id, name="episode.mp3")
    assert url == "https://s3.amazonaws.com/test-bucket/signed"

    # Delete job data
    store.delete_job_data(job_id=job_id)
    mock_s3.delete_objects.assert_called_once()
    assert not staged.exists()


def test_s3_missing_boto3():
    store = S3JobStore(bucket="bucket", client=None)
    with patch.dict("sys.modules", {"boto3": None}):
        with pytest.raises(RuntimeError, match="boto3 is required"):
            store._get_client()


def test_create_job_store_factory(tmp_path: Path):
    # Default is FileSystemJobStore
    with patch.dict(os.environ, {}, clear=True):
        store = create_job_store(base_dir=str(tmp_path))
        assert isinstance(store, FileSystemJobStore)
        assert store.base_dir == tmp_path

    # S3 without bucket raises ValueError
    with pytest.raises(ValueError, match="STORAGE_S3_BUCKET"):
        create_job_store("s3")

    # S3 with bucket creates S3JobStore
    store_s3 = create_job_store("s3", s3_bucket="my-bucket", staging_dir=str(tmp_path / "staging"))
    assert isinstance(store_s3, S3JobStore)
    assert store_s3.bucket == "my-bucket"


def test_purge_stale_entries(tmp_path: Path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from purge_stale_artifacts import purge_stale_entries

    target_dir = tmp_path / "processed"
    target_dir.mkdir()

    fresh_job = target_dir / "job-fresh"
    fresh_job.mkdir()
    (fresh_job / "output.txt").write_text("fresh")

    stale_job = target_dir / "job-stale"
    stale_job.mkdir()
    (stale_job / "output.txt").write_text("stale")

    # Artificially set mtime to 20 days ago
    old_time = time.time() - (20 * 86400)
    os.utime(stale_job, (old_time, old_time))

    # Dry run should identify stale job without deleting
    count, bytes_freed = purge_stale_entries(target_dir, max_age_days=14, dry_run=True)
    assert count == 1
    assert bytes_freed > 0
    assert stale_job.exists()
    assert fresh_job.exists()

    # Actual run should delete stale job
    count, bytes_freed = purge_stale_entries(target_dir, max_age_days=14, dry_run=False)
    assert count == 1
    assert not stale_job.exists()
    assert fresh_job.exists()
