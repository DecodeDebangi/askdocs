import hashlib

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from askdocs.chunk import Chunk
from askdocs.config import DATABASE_URL, EMBED_DIM, EMBED_MODEL

SCHEMA = f"""
create extension if not exists vector;

create table if not exists chunks (
    id           bigserial primary key,
    url          text not null,
    title        text not null,
    section      text,
    anchor       text,
    ord          int  not null,
    content      text not null,
    content_hash text not null,
    embedding    vector({EMBED_DIM}) not null,
    tsv          tsvector generated always as (
        setweight(to_tsvector('english', title), 'A') ||
        setweight(to_tsvector('english', coalesce(section, '')), 'B') ||
        setweight(to_tsvector('english', content), 'C')
    ) stored,
    unique (url, ord)
);

create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists chunks_tsv_idx on chunks using gin (tsv);
"""


LOG_SCHEMA = """
create table if not exists answers (
    id          bigserial primary key,
    question    text not null,
    answer      text not null,
    answered    boolean not null,
    cited       int[] not null,
    retrieve_ms int not null,
    llm_ms      int not null,
    created_at  timestamptz not null default now()
);
create index if not exists answers_unanswered_idx on answers (created_at desc) where not answered;
-- answered | escalated | no_sources | no_answer | error
alter table answers add column if not exists reason text;
"""


# Neon's pooled endpoint is PgBouncer in transaction mode, where a server-side prepared
# statement can land on a different backend. psycopg auto-prepares after 5 runs, so turn that off.
CONNECT_KWARGS = {"autocommit": True, "prepare_threshold": None}


def connect() -> psycopg.Connection:
    conn = psycopg.connect(DATABASE_URL, **CONNECT_KWARGS)
    conn.execute("create extension if not exists vector")
    register_vector(conn)
    return conn


def pool() -> ConnectionPool:
    def configure(conn: psycopg.Connection) -> None:
        register_vector(conn)

    return ConnectionPool(
        DATABASE_URL, min_size=1, max_size=5, kwargs=CONNECT_KWARGS, configure=configure, open=True
    )


def init_logs(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute(LOG_SCHEMA)


def log_answer(conn: psycopg.Connection, question: str, done: dict) -> None:
    """Every answer is stored, so the admin page can list the questions we couldn't answer."""
    conn.execute(
        """insert into answers (question, answer, answered, reason, cited, retrieve_ms, llm_ms)
           values (%s, %s, %s, %s, %s, %s, %s)""",
        (question, done["answer"], done["answered"], done["reason"], done["cited"],
         done["timings"]["retrieve_ms"], done["timings"]["llm_ms"]),
    )


def init_schema(conn: psycopg.Connection, reset: bool = False) -> None:
    if reset:
        conn.execute("drop table if exists chunks")
    stored = conn.execute(
        "select atttypmod from pg_attribute where attrelid = to_regclass('chunks') and attname = 'embedding'"
    ).fetchone()
    if stored and stored[0] != EMBED_DIM:
        raise SystemExit(
            f"chunks.embedding has {stored[0]} dimensions but {EMBED_MODEL} gives {EMBED_DIM}. "
            "Run `askdocs ingest --reset` to rebuild the index for this model."
        )
    conn.execute(SCHEMA)


def page_hash(chunks: list[Chunk]) -> str:
    # The model is part of the hash, so switching models re-embeds every page.
    h = hashlib.sha1(f"{EMBED_MODEL}\x00{chunks[0].title}".encode())
    for c in chunks:
        h.update(f"{c.section}\x00{c.content}\x00".encode())
    return h.hexdigest()


def stored_hash(conn: psycopg.Connection, url: str) -> str | None:
    row = conn.execute("select content_hash from chunks where url = %s limit 1", (url,)).fetchone()
    return row[0] if row else None


def replace_page(conn: psycopg.Connection, chunks: list[Chunk], embeddings: list[np.ndarray]) -> None:
    """Swap a page's chunks in one transaction, so search never sees half a page."""
    url, digest = chunks[0].url, page_hash(chunks)
    with conn.transaction():
        conn.execute("delete from chunks where url = %s", (url,))
        with conn.cursor() as cur:
            cur.executemany(
                """insert into chunks (url, title, section, anchor, ord, content, content_hash, embedding)
                   values (%s, %s, %s, %s, %s, %s, %s, %s)""",
                [(c.url, c.title, c.section, c.anchor, c.ord, c.content, digest, e) for c, e in zip(chunks, embeddings)],
            )


def delete_missing(conn: psycopg.Connection, keep_urls: set[str]) -> int:
    """Remove pages that are no longer in the crawl."""
    stored = {r[0] for r in conn.execute("select distinct url from chunks")}
    gone = list(stored - keep_urls)
    if gone:
        conn.execute("delete from chunks where url = any(%s)", (gone,))
    return len(gone)
