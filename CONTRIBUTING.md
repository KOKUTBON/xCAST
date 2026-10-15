# Contributing

Thank you for helping improve Thinking in Code. Contributions are welcome for the PDF processing pipeline, citation quality, retrieval, TTS and audio providers, API and worker reliability, documentation, testing, and accessibility.

## Before you start

- Search existing issues and pull requests before opening a duplicate.
- Use an issue to discuss substantial features, architecture changes, new providers, or changes to public contracts.
- Keep security reports private and follow [SECURITY.md](SECURITY.md).
- Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) in all project spaces.

## Development setup

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install all workspace packages in editable mode:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e libs/contracts -e libs/podcast -e libs/client -e services/api -e services/worker
```

4. Copy the example configuration when running the services locally:

```bash
cp services/api/.env.example services/api/.env
cp services/worker/.env.example services/worker/.env
```

5. Run quality checks before opening a pull request:

```bash
ruff check .
pytest -q
```

## Branch and PR workflow

- Create a short, descriptive branch for one focused change.
- Avoid mixing formatting, dependency, and behavioral changes without a clear reason.
- Explain the problem, the chosen approach, and any compatibility or security implications.
- List the exact validation commands and results.
- Link the relevant issue when one exists.
- Update documentation and examples when behavior changes.

## Coding guidelines

- Keep HTTP concerns in `services/api`, job execution in `services/worker`, shared schemas in `libs/contracts`, and pipeline behavior in `libs/podcast`.
- Extend a port or adapter for provider-specific behavior instead of coupling an external SDK to the application layer.
- Preserve backward compatibility for API fields, job states, artifact names, and CLI behavior unless a change is explicitly documented.
- Validate paths, uploads, identifiers, and untrusted text at system boundaries.
- Add meaningful tests for behavioral changes and regressions.
- Use clear names, type hints, and concise comments that explain decisions rather than syntax.

## Testing

Run the complete local checks:

```bash
ruff check .
pytest -q
```

For Docker changes, also validate the Compose file and build the affected images:

```bash
docker compose config -q
docker compose build api worker
```

Provider integrations should use deterministic fakes or mocks in the regular test suite. Document optional manual tests that require a model, credential, GPU, or external service.

## Documentation expectations

When architecture or behavior changes, update the relevant files:

- `README.md` for public setup and usage;
- `docs/architecture.md` or the focused design document;
- an ADR under `docs/adr/` for a lasting architectural decision;
- the `.env.example` files for new or changed configuration;
- `CHANGELOG.md` for user-visible changes.

## Licensing contributions

By submitting a contribution, you represent that you have the right to provide it under the repository's current license. Do not include third-party source, models, prompts, datasets, recordings, images, or other assets unless their license permits redistribution and all required notices are included.

## Community

By participating, you agree to follow [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## Community participation

Follow the [communication guidelines](COMMUNICATION.md) and [organizational governance](GOVERNANCE.md). Keep security and conduct reports confidential and use a verified private channel; never include sensitive details in a public issue. Maintainers verify the reporting contacts and channels listed in the [readiness checklist](RELEASE_CHECKLIST.md).

## KOKUTBON contribution principles

Contribute under the existing **MIT** license in [LICENSE](LICENSE). You retain copyright in your work. Submit only work you are entitled to share, identify third-party sources and preserve their notices. No copyright assignment or paid membership is required.

Open an issue for substantial proposals, then submit a focused pull request from a branch or fork. Describe the problem, implementation, relevant checks and any privacy, accessibility, migration or safety impact. Use synthetic fixtures and sanitized logs. Maintainer review and passing relevant CI checks are expected before merging. A sole maintainer may merge their own change after checks pass and must record the rationale; no fictitious second reviewer is required.

Small documentation, translation, accessibility and reproducibility improvements are welcome. Funding does not determine review priority. Follow [communication guidelines](COMMUNICATION.md) and [the sponsorship policy](SPONSORSHIP.md).
