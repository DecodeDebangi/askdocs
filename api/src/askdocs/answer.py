"""Retrieve, decide whether we can answer, then stream a cited answer.

Three guards against wrong answers:
1. Questions matching ESCALATE_PATTERN (disputes, chargebacks, legal) go to a human
   before any search, because those need someone who can act on the account.
2. If no source scores at least min_score() (reranker score, or cosine similarity
   with RERANK=none), nothing relevant was found, so we hand off without calling the LLM.
3. The prompt tells the model to reply NO_ANSWER when the sources don't cover the
   question. The first tokens are held back until we know it isn't that marker.

Every done event carries a `reason`: answered, escalated, no_sources, no_answer or error.
"""

import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass

import psycopg
import httpx
from openai import APIError, OpenAI

from askdocs import config
from askdocs.rerank import rerank
from askdocs.search import Hit, search

CANDIDATES = 20
# Without a reranker, hybrid search order is rougher, so the LLM gets more sources to pick from.
MAX_SOURCES = 5 if config.RERANK == "local" else 8
MAX_CONTEXT_CHARS = config.CONTEXT_CHARS
NO_ANSWER_MARKER = "NO_ANSWER"
HANDOFF_MESSAGE = (
    "I couldn't find an answer to this, so I don't want to guess. "
    "I've flagged your question for the team, and someone will follow up."
)
BUSY_MESSAGE = "I'm getting a lot of questions right now. Please try again in a minute."
ESCALATION_MESSAGE = (
    "This is something our team needs to handle directly. "
    "I've passed your question on, and someone will get back to you."
)

SYSTEM_PROMPT = """You are the support assistant for {product}. Answer the user's latest question using ONLY the numbered sources sent with it. Earlier messages are context only: their sources are gone.

The sources were found by an automatic search, so they may be about a different topic that only shares some words with the question. Requests that need a person to look up or change a specific order, payment or account, billing disputes and legal matters are for the human support team. General policy questions (like how refunds work) are answered from the sources.

Rules:
- If the sources do not contain the information needed to answer, reply with exactly {marker} and nothing else. Do not explain, apologize or answer from general knowledge.
- A source that says something is not allowed, not available or not covered IS an answer: reply "No" and explain what the source says.
- If the question names a specific case (a country, a store, a product) that a source's general rule covers, apply the rule and say which rule you applied. For example, "we only ship to Canada and the UK" answers "do you ship to Brazil?".
- After every sentence that uses a source, cite it with its number in square brackets, like [1] or [2][3].
- Never invent API names, settings, limits or prices that are not in the sources.
- Never state a rule more broadly than the source does. If a source covers only a specific case (one plan, one product, one kind of charge), say exactly which case it covers.
- Be concise and practical. Include short code examples from the sources when they help."""

# The sources travel with the question they were found for: put up front, before a
# conversation, they lose out to it, and a small model starts replying NO_ANSWER.
QUESTION_PROMPT = """Sources:
{sources}

Question: {question}"""

_CITATION = re.compile(r"\[(\d+)\]")


@dataclass
class Source:
    n: int
    title: str
    section: str | None
    url: str
    score: float


def rank(conn: psycopg.Connection, question: str) -> list[tuple[Hit, float]]:
    """Top sources with a relevance score: reranker score, or cosine similarity without one."""
    hits = search(conn, question, CANDIDATES)
    if config.RERANK == "local":
        return rerank(question, hits, MAX_SOURCES)
    return [(h, h.similarity) for h in hits[:MAX_SOURCES]]


def min_score() -> float:
    return config.MIN_RERANK_SCORE if config.RERANK == "local" else config.MIN_SIMILARITY


def retrieve(conn: psycopg.Connection, question: str) -> list[tuple[Hit, float]]:
    return [(h, s) for h, s in rank(conn, question) if s >= min_score()]


def build_context(ranked: list[tuple[Hit, float]]) -> tuple[str, list[Source]]:
    blocks, sources, used = [], [], 0
    for hit, score in ranked:
        remaining = MAX_CONTEXT_CHARS - used
        if remaining < 200 and sources:
            break
        text = hit.content[:remaining]
        n = len(sources) + 1
        where = hit.title if not hit.section else f"{hit.title} > {hit.section}"
        blocks.append(f"[{n}] {where}\n{text}")
        sources.append(Source(n, hit.title, hit.section, hit.link, round(score, 2)))
        used += len(text)
    return "\n\n".join(blocks), sources


def cited_numbers(answer: str, n_sources: int) -> list[int]:
    return sorted({int(n) for n in _CITATION.findall(answer) if 1 <= int(n) <= n_sources})


def llm() -> OpenAI:
    # Free tiers allow only a few requests per minute; the client backs off and retries on 429.
    return OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY, max_retries=6)


def answer_stream(
    conn: psycopg.Connection, question: str, history: list[dict] | None = None
) -> Iterator[dict]:
    """Yield events: sources, then token*, then done."""
    if should_escalate(question):
        yield {"type": "sources", "sources": []}
        yield {"type": "token", "text": ESCALATION_MESSAGE}
        yield _done(ESCALATION_MESSAGE, [], "escalated", retrieve_ms=0, llm_ms=0)
        return

    started = time.perf_counter()
    try:
        ranked = retrieve(conn, question)
    except httpx.HTTPError as e:  # embedding API rate limit or outage
        yield {"type": "sources", "sources": []}
        yield {"type": "token", "text": BUSY_MESSAGE}
        yield {**_done(BUSY_MESSAGE, [], "error", retrieve_ms=0, llm_ms=0), "error": type(e).__name__}
        return
    retrieve_ms = round((time.perf_counter() - started) * 1000)

    if not ranked:
        yield {"type": "sources", "sources": []}
        yield {"type": "token", "text": HANDOFF_MESSAGE}
        yield _done(HANDOFF_MESSAGE, [], "no_sources", retrieve_ms=retrieve_ms, llm_ms=0)
        return

    context, sources = build_context(ranked)
    yield {"type": "sources", "sources": [asdict(s) for s in sources]}

    messages = build_messages(question, context, history)

    llm_started = time.perf_counter()
    answer, held, released = "", "", False
    try:
        stream = llm().chat.completions.create(
            model=config.LLM_MODEL, messages=messages, temperature=0.1, stream=True
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            answer += delta
            if released:
                yield {"type": "token", "text": delta}
                continue
            held += delta
            stripped = held.lstrip()
            if NO_ANSWER_MARKER.startswith(stripped) or stripped.startswith(NO_ANSWER_MARKER):
                continue  # is (or might still become) the marker: never show it
            released = True
            yield {"type": "token", "text": held}
    except APIError as e:
        # Rate limit or provider outage: the docs may well have the answer, so this is not a handoff.
        llm_ms = round((time.perf_counter() - llm_started) * 1000)
        yield {"type": "token", "text": ("\n\n" if released else "") + BUSY_MESSAGE}
        yield {**_done(BUSY_MESSAGE, [], "error", retrieve_ms=retrieve_ms, llm_ms=llm_ms),
               "error": type(e).__name__}
        return
    llm_ms = round((time.perf_counter() - llm_started) * 1000)

    if answer.strip().startswith(NO_ANSWER_MARKER):
        yield {"type": "token", "text": HANDOFF_MESSAGE}
        yield _done(HANDOFF_MESSAGE, [], "no_answer", retrieve_ms=retrieve_ms, llm_ms=llm_ms)
        return
    if not released and held:
        yield {"type": "token", "text": held}
    yield _done(answer, cited_numbers(answer, len(sources)), "answered", retrieve_ms=retrieve_ms, llm_ms=llm_ms)


def build_messages(question: str, context: str, history: list[dict] | None = None) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(product=config.PRODUCT_NAME, marker=NO_ANSWER_MARKER)}]
    for m in (history or [])[-6:]:
        # Old citation numbers point into an earlier source list; left in, they get reused.
        content = re.sub(r"\s*\[\d+\]", "", m["content"]) if m["role"] == "assistant" else m["content"]
        messages.append({"role": m["role"], "content": content})
    messages.append({"role": "user", "content": QUESTION_PROMPT.format(sources=context, question=question)})
    return messages


def should_escalate(question: str) -> bool:
    return bool(config.ESCALATE_PATTERN) and re.search(config.ESCALATE_PATTERN, question, re.I) is not None


def _done(answer: str, cited: list[int], reason: str, retrieve_ms: int, llm_ms: int) -> dict:
    return {
        "type": "done",
        "answer": answer,
        "cited": cited,
        "answered": reason == "answered",
        # An LLM error is not a docs gap, so it doesn't go to the team.
        "handoff": reason in ("escalated", "no_sources", "no_answer"),
        "reason": reason,
        "timings": {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms},
    }
