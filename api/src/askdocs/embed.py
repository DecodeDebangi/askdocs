"""Text embeddings, from a local model or the Gemini API (EMBED_PROVIDER).

Gemini embeds documents and queries differently (taskType), like bge's query prefix.
"""

import time
from functools import cache

import httpx
import numpy as np

from askdocs import config

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
GEMINI_BATCH = 100  # API maximum per request
# The free tier counts every text in a batch as one request, 100 per minute. A batch that
# would cross the limit is rejected whole, so bulk ingest sends 45 texts at least 30 s apart.
PACED_BATCH, PACED_INTERVAL = 45, 30.0
_last_paced = float("-inf")  # across calls, since ingest embeds one group at a time


@cache
def model():
    # Imported here so the gemini provider never loads onnxruntime.
    from fastembed import TextEmbedding

    return TextEmbedding(config.EMBED_MODEL, threads=config.MODEL_THREADS)


@cache
def _client() -> httpx.Client:
    return httpx.Client(timeout=60, headers={"x-goog-api-key": config.GEMINI_API_KEY})


def _gemini(texts: list[str], task: str, patient: bool) -> list[np.ndarray]:
    # The free tier allows roughly 100 texts a minute. Bulk ingest waits out the window;
    # a live question retries briefly, then fails fast so the user sees a busy message.
    retries, wait = (15, 60) if patient else (2, 2)
    size = PACED_BATCH if patient else GEMINI_BATCH
    out: list[np.ndarray] = []
    url = GEMINI_URL.format(model=config.EMBED_MODEL)
    for i in range(0, len(texts), size):
        if patient:
            global _last_paced
            time.sleep(max(0.0, _last_paced + PACED_INTERVAL - time.monotonic()))
            _last_paced = time.monotonic()
        body = {"requests": [{
            "model": f"models/{config.EMBED_MODEL}",
            "content": {"parts": [{"text": t}]},
            "taskType": task,
            "outputDimensionality": config.EMBED_DIM,
        } for t in texts[i:i + size]]}
        for attempt in range(retries + 1):
            resp = _client().post(url, json=body)
            if resp.status_code in (429, 500, 503) and attempt < retries:
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        out += [np.asarray(e["values"], dtype=np.float32) for e in resp.json()["embeddings"]]
    return out


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    if config.EMBED_PROVIDER == "gemini":
        return _gemini(texts, "RETRIEVAL_DOCUMENT", patient=True)
    return list(model().passage_embed(texts, batch_size=64))


def embed_query(text: str) -> np.ndarray:
    if config.EMBED_PROVIDER == "gemini":
        return _gemini([text], "RETRIEVAL_QUERY", patient=False)[0]
    # query_embed adds the instruction prefix bge models expect for queries.
    return next(iter(model().query_embed(text)))
