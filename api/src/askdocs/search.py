"""Hybrid retrieval: full-text (BM25-like ts_rank) and vector search, merged with
Reciprocal Rank Fusion. Keyword search catches exact names like `supabase.auth.signUp`
that embeddings blur; vector search catches questions phrased differently from the docs.
"""

from dataclasses import dataclass

import psycopg

from askdocs.embed import embed_query

RRF_K = 60
CANDIDATES = 40

HYBRID_SQL = """
with vec as (
    select id, row_number() over () as rank
    from (select id from chunks order by embedding <=> %(q)s limit %(n)s) v
),
kw as (
    select id, row_number() over (order by score desc) as rank
    from (
        select id, ts_rank_cd(tsv, query) as score
        from chunks, websearch_to_tsquery('english', %(text)s) query
        where tsv @@ query
        order by score desc
        limit %(n)s
    ) k
)
select c.url, c.title, c.section, c.anchor, c.content,
       1 - (c.embedding <=> %(q)s) as similarity,
       vec.rank as vec_rank, kw.rank as kw_rank,
       coalesce(1.0 / (%(rrf)s + vec.rank), 0) + coalesce(1.0 / (%(rrf)s + kw.rank), 0) as score
from vec
full outer join kw using (id)
join chunks c using (id)
order by score desc
limit %(k)s
"""


@dataclass
class Hit:
    url: str
    title: str
    section: str | None
    anchor: str | None
    content: str
    similarity: float
    vec_rank: int | None
    kw_rank: int | None
    score: float

    @property
    def link(self) -> str:
        return f"{self.url}#{self.anchor}" if self.anchor else self.url


def search(conn: psycopg.Connection, query: str, k: int = 5) -> list[Hit]:
    params = {"q": embed_query(query), "text": query, "n": CANDIDATES, "rrf": RRF_K, "k": k}
    return [Hit(*row) for row in conn.execute(HYBRID_SQL, params).fetchall()]
