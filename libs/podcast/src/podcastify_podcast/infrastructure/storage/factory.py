from __future__ import annotations

import os
from pathlib import Path

from podcastify_podcast.application.ports import JobStore
from podcastify_podcast.infrastructure.storage.fs_store import FileSystemJobStore
from podcastify_podcast.infrastructure.storage.s3_store import S3JobStore


def create_job_store(
    backend: str | None = None,
    *,
    base_dir: str | Path | None = None,
    s3_bucket: str | None = None,
    s3_prefix: str | None = None,
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    staging_dir: str | Path | None = None,
) -> JobStore:
    """Factory to instantiate the configured JobStore implementation."""
    selected_backend = (backend or os.getenv("STORAGE_BACKEND", "local")).strip().lower()

    if selected_backend == "s3":
        bucket = s3_bucket or os.getenv("STORAGE_S3_BUCKET")
        if not bucket:
            raise ValueError(
                "STORAGE_S3_BUCKET environment variable (or s3_bucket parameter) is required when STORAGE_BACKEND=s3"
            )
        prefix = s3_prefix if s3_prefix is not None else os.getenv("STORAGE_S3_PREFIX", "artifacts")
        endpoint_url = s3_endpoint_url or os.getenv("STORAGE_S3_ENDPOINT_URL")
        region = s3_region or os.getenv("STORAGE_S3_REGION", "us-east-1")
        access_key = os.getenv("STORAGE_S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("STORAGE_S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
        local_staging = staging_dir or os.getenv("STORAGE_STAGING_DIR", "data/staging")

        return S3JobStore(
            bucket=bucket,
            prefix=prefix,
            staging_dir=str(local_staging),
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    # Default to FileSystemJobStore
    data_dir = os.getenv("DATA_DIR", "data")
    resolved_base = base_dir or os.getenv("STORAGE_LOCAL_DIR", str(Path(data_dir) / "processed"))
    return FileSystemJobStore(base_dir=str(resolved_base))
