"""Official Python SDK and CLI client for Thinking in Code (Podcastify)."""

from podcastify_client.client import ClientError, JobTimeoutError, ThinkingInCodeClient

__all__ = ["ThinkingInCodeClient", "ClientError", "JobTimeoutError"]
__version__ = "0.1.0"
