# Security

## Security model

This repository currently targets local development and self-hosted use. The default API has no authentication until `API_KEY` is set. The supplied Compose stack binds published ports to localhost; keep them behind a trusted boundary unless you add deployment-specific access controls.

The optional API key is a shared secret. It does not provide accounts, authorization scopes, per-job ownership, tenant isolation, abuse prevention, or rate limiting.

## Supported versions

Security fixes are applied to the latest revision of the default branch. There is currently no maintained long-term-support release line. Before reporting an issue, reproduce it against the latest revision when practical.

## Report a vulnerability

Use GitHub's private vulnerability reporting feature for this repository if it is enabled. Otherwise, contact the maintainer through a private channel listed on the maintainer's GitHub profile. Do not disclose exploit details, credentials, uploaded documents, or personal data in a public issue.

Include:

- the affected commit or version;
- the affected component and configuration;
- a minimal reproduction or proof of concept;
- the expected impact and required attacker access;
- any suggested mitigation;
- whether the issue has been disclosed elsewhere.

Maintainers will coordinate validation, remediation, and disclosure through the private report. No response-time or bounty guarantee is currently offered.

## Operational guidance

- Keep API and worker environment files out of version control; use the provided `.env.example` files only as templates.
- Generate a strong, unique `API_KEY` before any shared deployment, rotate it after suspected exposure, and transmit it only over HTTPS.
- Restrict API, Redis, Ollama, object storage, and metrics endpoints at the network boundary.
- Limit access to uploaded PDFs, feedback, generated artifacts, object storage, and logs. Configure and run retention cleanup for deployed instances.
- Review provider credentials and model/data transfer implications when enabling remote script or TTS providers.
- Pin and review container images and Python dependency updates before production rollout.
- Back up only the data that must be retained, encrypt sensitive storage, and test deletion and recovery procedures.

## Secret exposure

If a credential is committed or logged, revoke it at the provider first, remove it from the current tree, and assess whether Git history, build artifacts, caches, or published images also contain it. Adding a path to `.gitignore` does not remove an existing secret.

## Deployment boundary

The provided Docker Compose configuration is for local development. A public deployment requires an authenticated reverse proxy or equivalent ingress, HTTPS, request-size limits, rate limiting, monitoring, backups, and an explicit data-retention policy.

## Private reporting contact

Email [kokutbon@gmail.com](mailto:kokutbon@gmail.com) with subject `[xCAST] Security report`. Include affected version/commit, reproduction using synthetic data, preconditions and impact. Do not include live credentials or personal data. This mailbox is the fallback while the repository is private or GitHub's reporting form is unavailable.

After publication, prefer [GitHub private vulnerability reporting](https://github.com/KOKUTBON/xCAST/security/advisories/new) when enabled. Acknowledgment and remediation depend on maintainer availability; no response deadline is guaranteed. Coordinate disclosure and fixes privately.
