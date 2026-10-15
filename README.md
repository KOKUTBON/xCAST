# xCAST

A research-to-audio app that turns papers into cited scripts, transcripts, and spoken audio.

[Open the demo](https://kokutbon.github.io/xCAST/) · [Technical documentation](docs/architecture.md)

## Features

- Import research papers and organize source material.
- Review scripts with citations back to the source.
- Generate audio and follow along with transcripts.

## Screenshots

![xCAST main workspace](docs/screenshots/studio.png)

![xCAST detail view](docs/screenshots/listen.png)

## Technology

Python 3.11+, FastAPI, background workers, Redis, Ollama, pluggable text-to-speech.

## Run the demo locally

```sh
git clone https://github.com/KOKUTBON/xCAST.git
cd xCAST
python3 scripts/build_demo.py
python3 -m http.server 8000 --directory dist/pages
```

Open http://localhost:8000/. The browser demo uses sample data. See the technical documentation for the full application setup.

## License

[MIT License](LICENSE).
