# OO Design

## Layered model

The core engine in `libs/podcast` follows a clean OO boundary:

- Domain (`domain/`): pure models (`PageText`, `Chunk`) and core semantics.
- Application (`application/`): use cases (`GeneratePodcastFromPdf`, retrieval use case) and ports.
- Infrastructure (`infrastructure/`): adapters for LLM/TTS/PDF/vector store/audio/filesystem.

## Key classes and responsibilities

- `GeneratePodcastFromPdf`:
  - Orchestrates pipeline stages.
  - Keeps business flow independent from transport layer.
  - Produces typed `PodcastJobResult` and quality artifacts.
- Port interfaces (`application/ports.py`):
  - `PdfExtractor`, `Chunker`, `ScriptWriter`, `EmbeddingGenerator`, `VectorStore`, `TtsSynthesizer`, `AudioAssembler`, `JobStore`.
- Adapters:
  - Concrete implementations per provider (Ollama/OpenRouter, Piper/Coqui, local/FAISS).

## Object collaboration

1. Worker builds a configured use-case object graph.
2. Use case pulls text from `PdfExtractor`.
3. Chunking + script generation run through strategy-like adapters.
4. Optional embedding/vector indexing runs if adapters are configured.
5. Optional TTS/audio assembly runs if enabled.
6. `JobStore` persists artifacts without leaking storage details into use case logic.

## OO principles used

- Single responsibility:
  - API handles HTTP concerns.
  - Worker handles orchestration and retries.
  - Use case handles domain workflow.
- Open/closed:
  - New providers added by implementing a port, without changing use-case logic.
- Dependency inversion:
  - Use case depends on abstractions, not concrete external SDKs.

## Extension guidelines

- Add new providers by implementing the matching port in `infrastructure/`.
- Keep external SDK specifics out of domain/application layers.
- Add integration tests using stub/mocked adapters before wiring into worker config.
