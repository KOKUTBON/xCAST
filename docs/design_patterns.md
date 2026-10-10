# Design Patterns in Use

## 1) Ports and Adapters (Hexagonal)

- Where: `libs/podcast/application/ports.py` + `libs/podcast/infrastructure/*`.
- Why: isolate domain/application logic from external providers.
- Benefit: swap LLM, TTS, vector store, and PDF extractors with minimal risk.

## 2) Strategy Pattern

- Where: provider selection in worker (`_build_script_writer`, `_build_embeddings`, `_build_tts_and_audio`).
- Why: choose behavior at runtime from environment configuration.
- Benefit: same pipeline contract, different execution strategy.

## 3) Template-Method-like Orchestration

- Where: `GeneratePodcastFromPdf.run`.
- Why: fixed pipeline skeleton with optional stages (retrieval, TTS/audio).
- Benefit: predictable flow while preserving adapter-level variation.

## 4) Repository/Store Abstraction

- Where: `JobStore` port and `FileSystemJobStore`.
- Why: separate artifact persistence from business logic.
- Benefit: future migration to object storage without rewriting use cases.

## 5) Anti-corruption Layer

- Where: adapter modules wrapping external SDKs/APIs (Ollama, OpenRouter, Coqui, etc.).
- Why: keep third-party API quirks out of core models.
- Benefit: stable internal contracts and easier testing.

## 6) Fail-safe / Circuit-like Degradation

- Where: fallback script generation and non-fatal optional-stage failures in pipeline.
- Why: continue delivering useful artifacts when optional components fail.
- Benefit: graceful degradation and better user experience.

## 7) Queue Worker Reliability Patterns

- Where: `services/worker/src/podcastify_worker/main.py`.
- Patterns:
  - retry with exponential backoff,
  - dead-letter queue for exhausted failures,
  - claim lock for duplicate suppression.
- Benefit: operational resilience under transient/provider failures.
