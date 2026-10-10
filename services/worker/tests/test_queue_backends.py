from __future__ import annotations

import sys
import types
from pathlib import Path

from podcastify_worker import dir_queue, file_queue, redis_queue


def test_dir_queue_roundtrip(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    dir_queue.enqueue(queue_dir, "job-1", meta={"a": 1})
    dir_queue.enqueue(queue_dir, "job-2", meta={"a": 2})

    assert dir_queue.queue_depth(queue_dir) == 2
    first = dir_queue.dequeue(queue_dir)
    second = dir_queue.dequeue(queue_dir)
    assert {first["job_id"], second["job_id"]} == {"job-1", "job-2"}
    assert dir_queue.queue_depth(queue_dir) == 0


def test_file_queue_roundtrip(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    file_queue.enqueue(queue_file, "job-a", meta={"m": 1})
    file_queue.enqueue(queue_file, "job-b", meta={"m": 2})

    assert file_queue.queue_depth(queue_file) == 2
    first = file_queue.dequeue(queue_file)
    second = file_queue.dequeue(queue_file)
    assert first["job_id"] == "job-a"
    assert second["job_id"] == "job-b"
    assert file_queue.queue_depth(queue_file) == 0


def test_redis_queue_roundtrip_with_fake_client(monkeypatch) -> None:
    class FakeRedisClient:
        def __init__(self) -> None:
            self.items: list[tuple[str, float]] = []

        def zadd(self, key: str, mapping: dict[str, float]) -> None:  # noqa: ARG002
            payload, score = next(iter(mapping.items()))
            self.items.append((payload, float(score)))

        def zpopmax(self, key: str, count: int = 1):  # noqa: ARG002
            if not self.items:
                return []
            payload, score = sorted(self.items, key=lambda x: x[1], reverse=True).pop(0)
            self.items.remove((payload, score))
            return [(payload.encode("utf-8"), score)]

        def zcard(self, key: str) -> int:  # noqa: ARG002
            return len(self.items)

    client = FakeRedisClient()

    class FakeRedisClass:
        @staticmethod
        def from_url(url: str):  # noqa: ARG004
            return client

    fake_redis_module = types.ModuleType("redis")
    fake_redis_module.Redis = FakeRedisClass
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)

    score = redis_queue.enqueue(
        "redis://localhost:6379/0",
        "podcastify:jobs",
        job_id="job-r",
        priority=30.0,
        meta={"source": "test"},
    )
    assert score == 30.0
    assert redis_queue.queue_depth("redis://localhost:6379/0", "podcastify:jobs") == 1

    payload = redis_queue.dequeue("redis://localhost:6379/0", "podcastify:jobs")
    assert payload["job_id"] == "job-r"
    assert payload["score"] == 30.0
    assert payload["meta"]["source"] == "test"


def test_dir_queue_invalid_json_fallback(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    bad = queue_dir / "job-bad.json"
    bad.write_text("{bad json", encoding="utf-8")

    payload = dir_queue.dequeue(queue_dir)
    assert payload["job_id"] == "job-bad"


def test_file_queue_invalid_json_fallback(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.jsonl"
    queue_file.write_text("plain-job-id\n", encoding="utf-8")

    payload = file_queue.dequeue(queue_file)
    assert payload["job_id"] == "plain-job-id"
