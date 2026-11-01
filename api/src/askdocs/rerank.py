"""Cross-encoder reranking: reads the question and each candidate together, which fixes
cases where hybrid search ranks a chunk that shares words but not meaning.

ms-marco-MiniLM-L-6 (80 MB, local) gave the same top results as 40 full-length
candidates when given 20 candidates cut to 700 characters, in ~0.5 s instead of ~3 s on an M2.
"""

import threading
from functools import cache

from askdocs.config import MODEL_THREADS, RERANK_MODEL
from askdocs.search import Hit

PASSAGE_CHARS = 700
# Small batches keep peak memory under 512 MB (a batch of 20 needed more) at a small speed cost.
RERANK_BATCH = 4
# Each concurrent rerank adds ~30 MB at peak; 3 at once peaked at 459 MB. Cap it so a burst
# of visitors queues for a fraction of a second instead of crashing a 512 MB container.
_slots = threading.BoundedSemaphore(2)


@cache
def model():
    # Imported here so RERANK=none never loads onnxruntime.
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(RERANK_MODEL, threads=MODEL_THREADS)


def rerank(query: str, hits: list[Hit], k: int) -> list[tuple[Hit, float]]:
    if not hits:
        return []
    passages = [f"{h.title} > {h.section or ''}\n{h.content[:PASSAGE_CHARS]}" for h in hits]
    with _slots:
        scores = list(model().rerank(query, passages, batch_size=RERANK_BATCH))
    ranked = sorted(zip(hits, scores), key=lambda pair: pair[1], reverse=True)
    return ranked[:k]
