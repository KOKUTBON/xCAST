# ADR-0002: Worker retries, dead-letter, and claim locks

Date: 2026-03-09

## Decision

Add reliability controls in the worker:

- bounded retries with exponential backoff (`MAX_JOB_ATTEMPTS`, `RETRY_BACKOFF_S`)
- dead-letter persistence under `data/dead_letter/`
- per-job claim lock with stale lock recovery (`JOB_CLAIM_STALE_S`)
- configurable concurrent processing (`WORKER_MAX_CONCURRENT`)

## Rationale

- Provider/network failures are often transient and should not fail jobs immediately.
- Exhausted failures need durable context for debugging and incident response.
- Duplicate queue deliveries should not process the same job concurrently.
- Throughput must scale safely without sacrificing deterministic status transitions.

## Consequences

- Higher resilience and clearer operational debugging path.
- Slightly more worker complexity (attempt state + lock lifecycle).
- Requires documented tuning of retry/concurrency environment variables.
