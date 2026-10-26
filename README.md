# StudIA

Study assistant that answers questions in Tetum about your documents, using retrieval-augmented generation (RAG) over a notebook of uploaded files. The PRD in `docs/` is the contract for scope and behavior.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python package and project manager)
- Docker (for the PostgreSQL database)

## Database

PostgreSQL (+ the pgvector extension) runs in Docker, defined in
`docker-compose.yml`. On a fresh machine this creates the container
(`studia-pg`) and its data volume; every later call just starts it:

```bash
sudo docker compose up -d
```

The connection settings (host, port `5433`, credentials) come from `.env` —
copy `.env.example` to `.env` and fill in real values.

## Setup and run

```bash
uv sync                                   # install dependencies
uv run python manage.py migrate           # create schema in Postgres
uv run python manage.py runserver         # dev server (chat, notebooks)
uv run python manage.py qcluster          # background worker (ingestion)
```

Set the environment variables in `.env` — at minimum `DJANGO_SECRET_KEY`, the `DB_*` settings, and `GEMINI_API_KEY` (+ `LLM_MODEL`) for the chat.

## Tests

```bash
uv run pytest
```

Tests need the database running (they create a throwaway `test_` database).
