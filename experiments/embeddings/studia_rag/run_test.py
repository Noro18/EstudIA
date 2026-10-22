"""
Try the processor + chunker on a real file.

    python -m studia_rag.run_test path/to/lecture.pdf
    python -m studia_rag.run_test lecture.pdf --max-chars 800 --overlap 100 --show 5

Outputs (in --out-dir, default ./out):
  <doc_id>.chunks.json   list of chunks (id, index, page_start, page_end, text)
  <doc_id>.review.txt    human-readable chunks, so a Tetum speaker can write test questions
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from .processor import ExtractionError, process_document


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract and chunk a document for StudIA tests.")
    ap.add_argument("path")
    ap.add_argument("--doc-id", default=None)
    ap.add_argument("--max-chars", type=int, default=1200)
    ap.add_argument("--overlap", type=int, default=150)
    ap.add_argument("--min-chars", type=int, default=300)
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--show", type=int, default=3, help="print the first N chunks")
    args = ap.parse_args()

    try:
        doc = process_document(
            args.path,
            doc_id=args.doc_id,
            max_chars=args.max_chars,
            overlap_chars=args.overlap,
            min_chars=args.min_chars,
        )
    except ExtractionError as err:
        print(f"FAILED [{err.code}]: {err.message}")
        raise SystemExit(1)

    sizes = [c.char_count for c in doc.chunks]
    print(f"\nDocument : {doc.filename}  (id: {doc.doc_id})")
    print(f"Pages    : {doc.page_count}")
    print(f"Chunks   : {len(doc.chunks)}")
    if sizes:
        print(f"Size     : min {min(sizes)} / avg {int(statistics.mean(sizes))} / max {max(sizes)} chars")
    for w in doc.warnings:
        print(f"WARNING  : {w}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{doc.doc_id}.chunks.json"
    json_path.write_text(
        json.dumps([c.to_dict() for c in doc.chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    review_path = out_dir / f"{doc.doc_id}.review.txt"
    with review_path.open("w", encoding="utf-8") as f:
        for c in doc.chunks:
            pages = f"p.{c.page_start}" if c.page_start == c.page_end else f"p.{c.page_start}-{c.page_end}"
            f.write(f"=== [{c.id} | {pages} | {c.char_count} chars] ===\n{c.text}\n\n")

    print(f"\nWrote {json_path}\nWrote {review_path}")

    for c in doc.chunks[: args.show]:
        preview = c.text[:200].replace("\n", " ")
        print(f"\n[{c.id}] pages {c.page_start}-{c.page_end}, {c.char_count} chars\n  {preview}...")

    print(
        "\nLoad into the embedding comparison script with:\n"
        f'  chunks = {{c["id"]: c["text"] for c in json.load(open("{json_path}", encoding="utf-8"))}}'
    )


if __name__ == "__main__":
    main()
