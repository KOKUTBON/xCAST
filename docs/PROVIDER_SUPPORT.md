# Provider support and dependency policy

The supported source installation uses local keyword/vector retrieval and CPU speech synthesis. The core dependency locks are audited independently of optional model integrations.

ChromaDB, sentence-transformers and Qwen TTS are excluded from the supported optional installation. Their available dependency combinations include unresolved security advisories; Qwen TTS pins an affected Transformers release. Their adapters and installation dependencies have been removed from this release. Configuration selecting these providers is rejected. Do not install the old optional dependency bundle or expose these integrations to untrusted documents, model artifacts or public requests.

The optional audio-output bundle contains soundfile only. Existing provider interfaces allow future supported integrations once upstream fixes, compatibility tests and dependency audits pass. Model weights, licenses, hardware compatibility and external service accounts require a separate deployment review.
