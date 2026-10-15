# ADR-0004: Human-in-the-Loop Content Review Workflow

Date: 2026-09-17

## Decision

1. Introduce an `AWAITING_REVIEW` job status in `libs/contracts` and an opt-in `pause_at_script` parameter on `PodcastJobRequest` (default: `False`).
2. When `pause_at_script` is enabled:
   - Worker generates extraction, chunks, and podcast script (`script.json`, `script.md`, `transcript.txt`, `transcript.srt`).
   - Worker sets status to `AWAITING_REVIEW`, writes stage timing/quality logs, and yields the claim lock without marking the job as failed or retrying.
3. Provide API endpoints for script inspection and review:
   - `GET /v1/jobs/{job_id}/script`: returns the structured `EpisodeSegment`s and Markdown script.
   - `POST /v1/jobs/{job_id}/review`: accepts `action="approve"` (with optional edited segments) or `action="reject"`.
4. When approved:
   - API records `review.json` and updates `script.json` if edited segments are supplied.
   - API re-enqueues the job into the queue with status `QUEUED` and stage `reviewed`.
   - Worker resumes directly at TTS synthesis and audio assembly using the approved segments, skipping redundant extraction and LLM inference.
5. Provide interactive review and editing controls in the Web Studio UI.

## Rationale

- Generating audio via neural TTS (Piper, Coqui) and assembling audio mixes is computationally expensive and slow compared to script drafting.
- Enterprise research teams require editorial control to review pronunciation, emphasis, analogies, and factual grounding before public release.
- Allowing reviewers to edit segment titles, speaker names, and narration copy directly ensures higher production quality without re-running the full pipeline.

## Consequences

- Review is non-breaking and 100% opt-in. Automated and CI flows remain unaffected.
- Audio synthesis can resume immediately without re-spending LLM tokens.
- Reviewer actions are durably tracked in `data/jobs/<job_id>/review.json` for audit compliance.
