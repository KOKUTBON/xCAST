# Docker deployment

The maintained local stack is [`docker-compose.yaml`](../../docker-compose.yaml) at the repository root. It builds the API and worker from [`Dockerfile.api`](../../Dockerfile.api) and [`Dockerfile.worker`](../../Dockerfile.worker), and starts Redis and Ollama.

From the repository root:

```bash
docker compose up --build -d
docker compose exec ollama ollama pull llama3:instruct
```

The studio is served on <http://localhost:8000>. Runtime files are bind-mounted to `data/`. The default Compose file binds Redis, Ollama, and the API to localhost and leaves `API_KEY` empty; configure authentication and network exposure before sharing the stack.

Set the same queue and storage settings in the API and worker. See the two `.env.example` files for available options. The Python worker image includes FFmpeg and `espeak-ng`; audio generation still requires `ENABLE_TTS` and `ENABLE_AUDIO` plus a compatible voice provider.
