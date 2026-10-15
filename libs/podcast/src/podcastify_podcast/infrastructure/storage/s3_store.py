from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Any

from podcastify_podcast.application.ports import JobStore


class S3JobStore(JobStore):
    """S3-compatible artifact storage (AWS S3, MinIO, Cloudflare R2)."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "artifacts",
        staging_dir: str = "data/staging",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.staging_dir = Path(staging_dir)
        self.endpoint_url = endpoint_url
        self.region_name = region_name or "us-east-1"
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "boto3 is required for S3JobStore. Install it with: pip install 'libs/podcast[storage-s3]'"
            ) from e

        client_kwargs: dict[str, Any] = {"region_name": self.region_name}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url
        if self.aws_access_key_id and self.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = self.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = self.aws_secret_access_key

        self._client = boto3.client("s3", **client_kwargs)
        return self._client

    def _s3_key(self, job_id: str, name: str) -> str:
        clean_name = Path(name).name
        if self.prefix:
            return f"{self.prefix}/{job_id}/{clean_name}"
        return f"{job_id}/{clean_name}"

    def job_dir(self, job_id: str) -> Path:
        """Returns local scratch directory for staging synthesis and audio chunks."""
        d = self.staging_dir / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_artifact(self, *, job_id: str, name: str, content: bytes) -> str:
        key = self._s3_key(job_id, name)
        content_type, _ = mimetypes.guess_type(name)
        if not content_type:
            if name.endswith(".md"):
                content_type = "text/markdown"
            elif name.endswith(".srt"):
                content_type = "text/plain"
            elif name.endswith(".mp3"):
                content_type = "audio/mpeg"
            else:
                content_type = "application/octet-stream"

        client = self._get_client()
        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

        # Cache in local staging folder for use in subsequent pipeline steps if needed
        local_path = self.job_dir(job_id) / Path(name).name
        try:
            local_path.write_bytes(content)
        except Exception:
            pass

        return f"s3://{self.bucket}/{key}"

    def read_artifact(self, *, job_id: str, name: str) -> bytes:
        key = self._s3_key(job_id, name)
        client = self._get_client()
        try:
            resp = client.get_object(Bucket=self.bucket, Key=key)
            body = resp["Body"].read()
            return body
        except Exception as exc:
            # Handle NoSuchKey or 404
            err_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if err_code in {"NoSuchKey", "404"} or "NoSuchKey" in str(exc):
                raise FileNotFoundError(
                    f"Artifact {name} not found in s3://{self.bucket}/{key}"
                ) from exc
            raise

    def artifact_exists(self, *, job_id: str, name: str) -> bool:
        key = self._s3_key(job_id, name)
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def list_artifacts(self, *, job_id: str) -> list[str]:
        client = self._get_client()
        prefix = f"{self.prefix}/{job_id}/" if self.prefix else f"{job_id}/"
        try:
            resp = client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            contents = resp.get("Contents", [])
            artifacts = []
            for item in contents:
                k = item.get("Key", "")
                if k and not k.endswith("/"):
                    artifacts.append(Path(k).name)
            return sorted(artifacts)
        except Exception:
            return []

    def delete_job_data(self, *, job_id: str) -> None:
        client = self._get_client()
        prefix = f"{self.prefix}/{job_id}/" if self.prefix else f"{job_id}/"
        try:
            resp = client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            contents = resp.get("Contents", [])
            if contents:
                delete_keys = [{"Key": item["Key"]} for item in contents if "Key" in item]
                if delete_keys:
                    client.delete_objects(Bucket=self.bucket, Delete={"Objects": delete_keys})
        except Exception:
            pass

        # Also purge local staging
        staging = self.staging_dir / job_id
        if staging.exists() and staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)

    def get_download_url(self, *, job_id: str, name: str, expires_in: int = 3600) -> str | None:
        key = self._s3_key(job_id, name)
        client = self._get_client()
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return str(url)
        except Exception:
            return None
