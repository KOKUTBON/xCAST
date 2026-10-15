from __future__ import annotations

import pytest
from podcastify_worker import main as worker_main


@pytest.mark.parametrize("provider", ["qwen", "unknown"])
def test_build_tts_rejects_removed_or_unknown_provider(monkeypatch, provider) -> None:
    monkeypatch.setenv("ENABLE_TTS", "true")
    monkeypatch.setenv("ENABLE_AUDIO", "true")
    monkeypatch.setenv("TTS_PROVIDER", provider)
    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        worker_main._build_tts_and_audio()


def test_embeddings_rejects_removed_provider(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence-transformers")
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        worker_main._build_embeddings()


def test_embeddings_rejects_removed_store(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "chroma")
    with pytest.raises(ValueError, match="Unsupported vector store"):
        worker_main._build_embeddings()


def test_build_tts_and_audio_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_TTS", "false")
    monkeypatch.setenv("ENABLE_AUDIO", "false")

    tts, audio = worker_main._build_tts_and_audio()

    assert tts is None
    assert audio is None
