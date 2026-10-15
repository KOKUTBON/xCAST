from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from podcastify_api import queue


def test_enqueue_dir_and_file(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue_dir"
    queue_file = tmp_path / "queue.jsonl"

    dir_path = queue.enqueue_dir(queue_dir, "job-1", meta={"minutes": 8})
    file_path = queue.enqueue_file(queue_file, "job-2", meta={"minutes": 6})

    assert Path(dir_path).exists()
    payload = json.loads(Path(dir_path).read_text(encoding="utf-8"))
    assert payload["job_id"] == "job-1"
    assert payload["meta"]["minutes"] == 8

    assert Path(file_path).exists()
    lines = Path(file_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload2 = json.loads(lines[0])
    assert payload2["job_id"] == "job-2"


def test_score_job_prefers_explicit_priority() -> None:
    score = queue._score_job(17.5, {"num_pdfs": 10, "minutes": 60})
    assert score == 17.5


def test_enqueue_redis_uses_zadd(monkeypatch) -> None:
    class FakeRedisClient:
        def __init__(self) -> None:
            self.args = None

        def zadd(self, key: str, mapping: dict[str, float]) -> None:
            self.args = (key, mapping)

    client = FakeRedisClient()

    class FakeRedisClass:
        @staticmethod
        def from_url(url: str):  # noqa: ARG004
            return client

    fake_redis_module = types.ModuleType("redis")
    fake_redis_module.Redis = FakeRedisClass
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)

    score = queue.enqueue_redis(
        "redis://localhost:6379/0", "podcastify:jobs", job_id="job-3", priority=42.0, meta={"x": 1}
    )
    assert score == 42.0
    key, mapping = client.args
    assert key == "podcastify:jobs"
    payload = next(iter(mapping))
    body = json.loads(payload)
    assert body["job_id"] == "job-3"
