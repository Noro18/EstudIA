"""
Chunker: list[Page] -> list[Chunk].

Strategy (simple, explainable, good enough to start):
  1. Break the document into "units": whole paragraphs when they fit, otherwise sentences
     (and, as a last resort, word groups). Every unit remembers which page it came from.
  2. Pack units into a chunk until adding the next one would exceed max_chars.
  3. Start the next chunk with a small overlap (the last few units of the previous chunk)
     so an idea sitting on a boundary appears whole in at least one chunk.
  4. A too-small final chunk is merged into the previous one.

Chunks flow across page boundaries, so a paragraph that continues on the next page stays
together. Each chunk records page_start and page_end for citations.

Sizes are in characters (rough guide: 1 token ~ 3-4 characters, and Tetum often needs
more tokens per character than English, so 1200 chars is roughly 300-400 tokens).
"""
from __future__ import annotations

import re
from typing import NamedTuple

from .models import Chunk, Page

# Split after . ! ? when followed by a capital letter, digit, quote or bracket.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÇÑ0-9\"“(\[])")


class Unit(NamedTuple):
    text: str
    page: int
    new_paragraph: bool   # True if this unit starts a paragraph (used when joining)


def _split_by_words(text: str, max_chars: int) -> list[str]:
    """Last resort for a 'sentence' longer than max_chars (tables, lists, bad extraction)."""
    pieces, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def _split_long_paragraph(text: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            pieces.append(sentence)
        else:
            pieces.extend(_split_by_words(sentence, max_chars))
    return pieces


def _to_units(pages: list[Page], max_chars: int) -> list[Unit]:
    units: list[Unit] = []
    for page in pages:
        for paragraph in page.paragraphs:
            pieces = [paragraph] if len(paragraph) <= max_chars else _split_long_paragraph(paragraph, max_chars)
            for i, piece in enumerate(pieces):
                units.append(Unit(piece, page.number, new_paragraph=(i == 0)))
    return units


def _join(units: list[Unit]) -> str:
    out = ""
    for i, u in enumerate(units):
        if i == 0:
            out = u.text
        else:
            out += ("\n\n" if u.new_paragraph else " ") + u.text
    return out


def _size(units: list[Unit]) -> int:
    return len(_join(units)) if units else 0


def _overlap_tail(units: list[Unit], overlap_chars: int) -> list[Unit]:
    """The last few units of a finished chunk whose total length fits in overlap_chars."""
    tail: list[Unit] = []
    total = 0
    for u in reversed(units):
        if total + len(u.text) > overlap_chars:
            break
        tail.insert(0, u)
        total += len(u.text) + 1
    return tail


def chunk_pages(
    pages: list[Page],
    doc_id: str = "doc",
    max_chars: int = 1200,
    overlap_chars: int = 150,
    min_chars: int = 300,
) -> list[Chunk]:
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    units = _to_units(pages, max_chars)
    groups: list[list[Unit]] = []     # finished chunks (as lists of units)
    current: list[Unit] = []
    carried = 0                       # how many units at the start of `current` are overlap

    for unit in units:
        if current and _size(current + [unit]) > max_chars:
            groups.append(current)
            tail = _overlap_tail(current, overlap_chars)
            # only keep the overlap if the new unit still fits next to it
            if tail and _size(tail + [unit]) > max_chars:
                tail = []
            current, carried = list(tail), len(tail)
        current.append(unit)

    if current and len(current) > carried:      # something new beyond pure overlap
        new_part = current[carried:]
        if groups and _size(new_part) < min_chars:
            groups[-1].extend(new_part)         # merge a tiny leftover into the previous chunk
        else:
            groups.append(current)

    chunks: list[Chunk] = []
    for i, group in enumerate(groups):
        text = _join(group)
        pages_in_chunk = [u.page for u in group]
        chunks.append(
            Chunk(
                id=f"{doc_id}-{i:04d}",
                index=i,
                page_start=min(pages_in_chunk),
                page_end=max(pages_in_chunk),
                text=text,
                char_count=len(text),
            )
        )
    return chunks
