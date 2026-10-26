"""Spike: compare SDK streaming surfaces + which Flash models answer right now.

Run from repo root:  uv run python -u experiments/sdk_stream_spike.py
Consumes a couple of tiny generation calls per responding model.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from google import genai
from google.genai import types

# Fast-fail client: 25 s timeout, no SDK retries (this spike must not hang;
# we have seen Google hang streams with zero bytes for minutes).
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(
        timeout=25000,
        retry_options=types.HttpRetryOptions(attempts=1),
    ),
)

MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
]

print("=== models.generate_content_stream across models ===")
for model in MODELS:
    try:
        chunks = list(client.models.generate_content_stream(model=model, contents="Say hi in two words."))
        first = chunks[0] if chunks else None
        print(f"{model:24s} OK  chunks={len(chunks)}", end="")
        if first is not None:
            print(f" text={str(first.text)[:20]!r} usage={first.usage_metadata}", end="")
        print()
    except Exception as e:
        print(f"{model:24s} {type(e).__name__} {getattr(e, 'code', '')}: {str(e)[:100]}")

print()
print("=== chunk anatomy (one model) ===")
try:
    for i, chunk in enumerate(client.models.generate_content_stream(model="gemini-flash-latest", contents="Count to three.")):
        um = chunk.usage_metadata
        print(f"chunk {i}: text={str(chunk.text)[:30]!r}")
        print(f"  usage: prompt={um.prompt_token_count} candidates={um.candidates_token_count} total={um.total_token_count}")
        if chunk.candidates and chunk.candidates[0].finish_reason:
            print(f"  finish_reason={chunk.candidates[0].finish_reason}")
except Exception as e:
    print(f"anatomy probe failed: {type(e).__name__} {getattr(e, 'code', '')}: {str(e)[:100]}")

print()
print(f"SDK surface check: client.interactions exists = {hasattr(client, 'interactions')}")
