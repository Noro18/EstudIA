"""Tune CPU embedding speed for SEA-LION: threads x batch_size on the SDD chunks."""
import json
import time

import torch
from sentence_transformers import SentenceTransformer

path = "out/24-2025-impar-ei0204703-09-system-design-document-for-e-learning-1.chunks.json"
texts = [c["text"] for c in json.load(open(path, encoding="utf-8"))]

model = SentenceTransformer("aisingapore/SEA-LION-ModernBERT-Embedding-300M", device="cpu")

print(f"{'threads':>8}{'batch':>8}{'s/chunk':>10}")
for threads in (4, 8):
    torch.set_num_threads(threads)
    model.encode(texts[:3])                  # warm-up after thread change (not timed)
    for batch in (8, 32):
        t = time.time()
        model.encode(texts, batch_size=batch, normalize_embeddings=True)
        per = (time.time() - t) / len(texts)
        print(f"{threads:>8}{batch:>8}{per:>10.3f}")
