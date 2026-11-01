from functools import cache

import numpy as np
from fastembed import TextEmbedding

from askdocs.config import EMBED_MODEL


@cache
def model() -> TextEmbedding:
    return TextEmbedding(EMBED_MODEL)


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    return list(model().passage_embed(texts, batch_size=64))


def embed_query(text: str) -> np.ndarray:
    # query_embed adds the instruction prefix bge models expect for queries.
    return next(iter(model().query_embed(text)))
