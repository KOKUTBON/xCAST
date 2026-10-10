# Thinking in Code Architecture

This document is the high-level architecture index. Detailed design docs are split by concern:

- `docs/system_design.md`: runtime topology, data flow, scalability, reliability.
- `docs/oo_design.md`: object-oriented boundaries and core abstractions.
- `docs/design_patterns.md`: concrete pattern usage in this repository.
- `docs/adr/`: architecture decisions and rationale over time.

## System overview

Thinking in Code is a local-first, service-oriented pipeline:

1. API accepts uploads and creates jobs.
2. Queue transports job IDs to worker processes.
3. Worker executes extraction -> chunking -> script generation -> optional retrieval -> optional TTS/audio.
4. Artifacts and status are written to filesystem-backed runtime storage.
5. API exposes status, SSE progress, metrics summary, and artifact downloads.

## Deployable units

- `services/api`: FastAPI surface, request validation, job registration, status/metrics endpoints, web studio.
- `services/worker`: long-running processor with retries, dead-letter handling, and configurable concurrency.
- `libs/contracts`: shared Pydantic models used by API/worker/core.
- `libs/podcast`: clean-architecture core with domain/application/infrastructure layers.

## Data boundaries

- Job input and status: `data/jobs/<job_id>/`.
- Processed outputs: `data/processed/<job_id>/`.
- Retry exhaustions (DLQ): `data/dead_letter/`.
- Feedback payloads: `data/feedback/`.
- Queue backends: filesystem queue, file queue, or Redis sorted set.

## Architectural properties

- Clear separation between transport (API/worker) and business logic (use cases in `libs/podcast`).
- Ports/adapters pattern for swappable providers (LLM, embedding, vector store, TTS, audio).
- Operational guardrails: upload validation, idempotent submission, worker retries, dead-letter, claim locks.
- Local-first deterministic artifacts for inspection and debugging.
