# ADR-0003: Pluggable storage backends and data retention policies

Date: 2026-09-17

## Decision

1. Expand the `JobStore` application port to support full artifact lifecycle management (`write_artifact`, `read_artifact`, `artifact_exists`, `list_artifacts`, `delete_job_data`, `get_download_url`, `job_dir`).
2. Implement `S3JobStore` supporting S3-compatible object storage (AWS S3, MinIO, Cloudflare R2) alongside the default `FileSystemJobStore`.
3. Provide a unified `create_job_store()` factory configured via environment variables (`STORAGE_BACKEND`, `STORAGE_S3_BUCKET`, `STORAGE_S3_PREFIX`, `STORAGE_S3_ENDPOINT_URL`, etc.).
4. Support presigned URL redirects in the API for efficient cloud artifact downloads without overloading the API server.
5. Provide an automated retention/cleanup utility (`scripts/purge_stale_artifacts.py`) to purge aged jobs, artifacts, and staging files based on configurable retention TTLs.

## Rationale

- Running worker clusters across multiple machines or container environments requires decoupled cloud object storage rather than local disk paths.
- Local filesystem storage remains default for zero-dependency local development and testing.
- Audio synthesis requires local staging scratch space before uploading to object storage.
- Long-running deployments accumulate large intermediate WAV/MP3 files and uploaded PDFs, necessitating automated data governance and retention pruning.

## Consequences

- Services can run headless in cloud environments with artifacts stored in S3/MinIO/R2.
- Optional dependency `boto3` is isolated in `libs/podcast[storage-s3]`.
- API download endpoints seamlessly redirect to presigned URLs when available.
- Retention cleanup can run as a periodic cron job or container task.
