"""
Compare embedding models on YOUR chunks and YOUR Tetum questions.

    python -m studia_rag.compare_embeddings \
        --chunks out/lecture.chunks.json out/laporan.chunks.json \
        --questions questions.json \
        --models bge-m3 e5-large

questions.json looks like:
[
  {"question": "Saida mak sustenta ekonomia Timor-Leste nian?",
   "chunk_ids": ["lecture-0003"],          # chunk(s) that contain the answer
   "type": "same_language"},               # optional label: same_language / cross_language / ...
  ...
]

For every model the script reports:
  recall@k : share of questions whose correct chunk is in the top k results
  MRR      : average of 1/rank of the first correct chunk (1.0 = always ranked first)
and lists the questions it got wrong, so you can see WHY (bad question? bad chunk? bad model?).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

KS = (1, 3, 5, 10)

MODELS = {
    "bge-m3": dict(id="BAAI/bge-m3"),
    "e5-large": dict(
        id="intfloat/multilingual-e5-large", q_prefix="query: ", p_prefix="passage: "
    ),
    "e5-small": dict(
        id="intfloat/multilingual-e5-small", q_prefix="query: ", p_prefix="passage: "
    ),
    "qwen3-0.6b": dict(id="Qwen/Qwen3-Embedding-0.6B", prompt_name="query"),
    "sea-lion-300m": dict(id="aisingapore/SEA-LION-ModernBERT-Embedding-300M"),
}


# ----------------------------------------------------------------- metrics (no model needed)


def evaluate(chunk_ids, chunk_vecs, q_vecs, questions):
    """Rank every chunk for every question. Vectors must be L2-normalised (dot = cosine)."""
    scores = q_vecs @ chunk_vecs.T
    order = np.argsort(-scores, axis=1)
    rows = []
    for qi, q in enumerate(questions):
        ranked = [chunk_ids[j] for j in order[qi]]
        gold = set(q["chunk_ids"])
        rank = next((r for r, cid in enumerate(ranked, start=1) if cid in gold), None)
        rows.append(
            {
                "question": q["question"],
                "type": q.get("type", "unspecified"),
                "gold": sorted(gold),
                "rank": rank,  # None can't happen unless corpus lacks the chunk
                "top3": ranked[:3],
            }
        )
    return rows


def summarize(rows, ks=KS):
    def agg(subset):
        n = len(subset)
        out = {
            f"recall@{k}": sum(1 for r in subset if r["rank"] and r["rank"] <= k) / n
            for k in ks
        }
        out["MRR"] = sum(1 / r["rank"] for r in subset if r["rank"]) / n
        out["n"] = n
        return out

    result = {"overall": agg(rows)}
    for t in sorted({r["type"] for r in rows}):
        result[t] = agg([r for r in rows if r["type"] == t])
    return result


# ----------------------------------------------------------------- model running


def run_model(name, cfg, chunk_ids, chunk_texts, questions):
    from sentence_transformers import SentenceTransformer

    print(f"\n=== {name} ({cfg['id']}) ===")
    model = SentenceTransformer(cfg["id"])

    # Silent truncation is a classic trap: warn if chunks exceed the model's input limit.
    limit = model.max_seq_length
    if limit and getattr(model, "tokenizer", None) is not None:
        lengths = [len(ids) for ids in model.tokenizer(chunk_texts)["input_ids"]]
        too_long = sum(1 for n in lengths if n > limit)
        print(
            f"max input {limit} tokens | longest chunk {max(lengths)} tokens | truncated chunks: {too_long}"
        )

    t0 = time.time()
    chunk_vecs = model.encode(
        [cfg.get("p_prefix", "") + t for t in chunk_texts],
        batch_size=16,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    embed_seconds = time.time() - t0

    q_kwargs = {"prompt_name": cfg["prompt_name"]} if "prompt_name" in cfg else {}
    q_vecs = model.encode(
        [cfg.get("q_prefix", "") + q["question"] for q in questions],
        batch_size=16,
        normalize_embeddings=True,
        **q_kwargs,
    )

    rows = evaluate(chunk_ids, chunk_vecs, q_vecs, questions)
    return {
        "model": cfg["id"],
        "dimensions": int(chunk_vecs.shape[1]),
        "embed_seconds": round(embed_seconds, 1),
        "summary": summarize(rows),
        "rows": rows,
    }


# ----------------------------------------------------------------- loading and reporting


def load_corpus(paths):
    corpus = {}
    for p in paths:
        for c in json.loads(Path(p).read_text(encoding="utf-8")):
            corpus[c["id"]] = c["text"]
    return corpus


def load_questions(path, corpus):
    questions = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = [
        q for q in questions if q.get("chunk_ids")
    ]  # skip unanswerable ones here
    unknown = {cid for q in questions for cid in q["chunk_ids"] if cid not in corpus}
    if unknown:
        raise SystemExit(
            f"These chunk_ids in questions.json do not exist in the chunk files: {sorted(unknown)}"
        )
    return questions


def print_summary(all_results):
    cols = ["recall@1", "recall@3", "recall@5", "recall@10", "MRR"]
    print("\n" + "=" * 78 + "\nRESULTS (overall)\n" + "=" * 78)
    print(
        f"{'model':<14}"
        + "".join(f"{c:>11}" for c in cols)
        + f"{'dims':>7}{'embed s':>9}"
    )
    for name, res in all_results.items():
        o = res["summary"]["overall"]
        print(
            f"{name:<14}"
            + "".join(f"{o[c]:>11.2f}" for c in cols)
            + f"{res['dimensions']:>7}{res['embed_seconds']:>9}"
        )

    print("\nBy question type (recall@5):")
    types = sorted(
        {t for r in all_results.values() for t in r["summary"] if t != "overall"}
    )
    print(f"{'model':<14}" + "".join(f"{t:>18}" for t in types))
    for name, res in all_results.items():
        cells = []
        for t in types:
            s = res["summary"].get(t)
            cells.append(f"{s['recall@5']:.2f} (n={s['n']})" if s else "-")
        print(f"{name:<14}" + "".join(f"{c:>18}" for c in cells))


def print_failures(name, rows, k=5, limit=8):
    misses = [r for r in rows if not r["rank"] or r["rank"] > k]
    print(f"\n[{name}] {len(misses)} question(s) missed in the top {k}:")
    for r in misses[:limit]:
        print(
            f"  - ({r['type']}) {r['question']}\n      expected {r['gold']} | found at rank {r['rank']} | top3 {r['top3']}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--chunks", nargs="+", required=True, help="one or more *.chunks.json files"
    )
    ap.add_argument("--questions", required=True)
    ap.add_argument(
        "--models", nargs="+", default=["bge-m3", "e5-large"], choices=list(MODELS)
    )
    ap.add_argument("--out-dir", default="out")
    args = ap.parse_args()

    corpus = load_corpus(args.chunks)
    questions = load_questions(args.questions, corpus)
    chunk_ids, chunk_texts = list(corpus), list(corpus.values())
    print(f"{len(chunk_ids)} chunks, {len(questions)} questions")

    all_results = {}
    for name in args.models:
        all_results[name] = run_model(
            name, MODELS[name], chunk_ids, chunk_texts, questions
        )

    print_summary(all_results)
    for name, res in all_results.items():
        print_failures(name, res["rows"])

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "embedding_results.json").write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nFull results saved to {out / 'embedding_results.json'}")


if __name__ == "__main__":
    main()
