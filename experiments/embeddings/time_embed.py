"""Time how long it takes to embed the SDD chunks with SEA-LION (CPU)."""
import json
import time

import torch
from sentence_transformers import SentenceTransformer

torch.set_num_threads(4)

path = "out/24-2025-impar-ei0204703-09-system-design-document-for-e-learning-1.chunks.json"
chunks = json.load(open(path, encoding="utf-8"))
texts = [c["text"] for c in chunks]

t0 = time.time()
model = SentenceTransformer("aisingapore/SEA-LION-ModernBERT-Embedding-300M", device="cpu")
print(f"model load: {time.time() - t0:.0f} s")

model.encode(texts[:2])                      # warm-up, not timed
t = time.time()
model.encode(texts, batch_size=8, normalize_embeddings=True)
print(f"{(time.time() - t) / len(texts):.2f} seconds per chunk")
