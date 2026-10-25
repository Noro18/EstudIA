# StudIA

Study assistant that answers questions in Tetum about your documents, using retrieval-augmented generation (RAG) over a notebook of uploaded files. The PRD in `docs/` is the contract for scope and behavior.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python package and project manager)
- Docker (for the PostgreSQL database)

## Database

PostgreSQL runs in Docker. Start it before running the app or the tests:

```bash
sudo docker start studia-pg
```

The connection settings (host, port `5433`, credentials) come from `.env`.

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
