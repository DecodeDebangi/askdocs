"""Score the chatbot against a labelled question set.

Each line of the set is one question:
  answerable: {"id", "question", "answerable": true, "gold_pages": [...], "facts": [[alt, ...], ...]}
  unanswerable: {"id", "question", "answerable": false}

gold_pages are doc paths (any one counts). Each facts group must appear in the answer,
matching any of its alternatives, case-insensitively.

Retrieval-only mode skips the LLM: it scores hit@k and whether the relevance gate
hands off the right questions, in seconds instead of minutes.
"""

import json
import statistics
import time
from pathlib import Path
from urllib.parse import urldefrag

import psycopg

from askdocs import config
from askdocs.answer import MAX_SOURCES, answer_stream, min_score, rank

LLM_RETRIES = 4


def load_set(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def page_of(url: str) -> str:
    return urldefrag(url)[0].removeprefix(config.URL_PREFIX).strip("/")


def first_gold_rank(urls: list[str], gold: list[str]) -> int | None:
    for i, url in enumerate(urls, 1):
        if page_of(url) in gold:
            return i
    return None


def facts_found(answer: str, facts: list[list[str]]) -> bool:
    text = answer.lower()
    return all(any(alt.lower() in text for alt in group) for group in facts)


def check_gold_pages(conn: psycopg.Connection, items: list[dict]) -> list[str]:
    indexed = {page_of(r[0]) for r in conn.execute("select distinct url from chunks")}
    return [f"{it['id']}: {g}" for it in items for g in it.get("gold_pages", []) if g not in indexed]


def run_item(conn: psycopg.Connection, item: dict, retrieval_only: bool) -> dict:
    q = item["question"]
    started = time.perf_counter()
    ranked = rank(conn, q)
    retrieve_ms = (time.perf_counter() - started) * 1000
    top_score = ranked[0][1] if ranked else float("-inf")
    result = {
        "id": item["id"],
        "question": q,
        "answerable": item["answerable"],
        "top_score": round(float(top_score), 2),
        "retrieved": [h.link for h, _ in ranked],
        "gate_handoff": top_score < min_score(),
        "retrieve_ms": round(retrieve_ms),
    }
    if item["answerable"]:
        result["gold_rank"] = first_gold_rank(result["retrieved"], item["gold_pages"])
    if retrieval_only:
        return result

    for attempt in range(LLM_RETRIES + 1):
        started = time.perf_counter()
        events = list(answer_stream(conn, q))
        done = events[-1]
        if not done.get("error") or attempt == LLM_RETRIES:
            break
        wait = 20 * (attempt + 1)  # free tiers limit requests per minute
        print(f"      LLM {done['error']}, retrying in {wait}s")
        time.sleep(wait)
    if done.get("error"):
        result["error"] = done["error"]
    sources = next(e["sources"] for e in events if e["type"] == "sources")
    cited_urls = [s["url"] for s in sources if s["n"] in done["cited"]]
    result.update(
        answer=done["answer"],
        handoff=done["handoff"],
        cited=cited_urls,
        total_ms=round((time.perf_counter() - started) * 1000),
    )
    if item["answerable"]:
        result["facts_ok"] = not done["handoff"] and facts_found(done["answer"], item["facts"])
        result["cited_gold"] = first_gold_rank(cited_urls, item["gold_pages"]) is not None
    return result


def pct(n: int, d: int) -> str:
    return f"{n / d:.0%} ({n}/{d})" if d else "n/a"


def summarize(results: list[dict], retrieval_only: bool) -> dict[str, str]:
    ans = [r for r in results if r["answerable"]]
    una = [r for r in results if not r["answerable"]]
    s = {
        "retrieval hit@1": pct(sum(r["gold_rank"] == 1 for r in ans), len(ans)),
        f"retrieval hit@{MAX_SOURCES}": pct(sum(r["gold_rank"] is not None for r in ans), len(ans)),
        "gate: off-topic handed off": pct(sum(r["gate_handoff"] for r in una), len(una)),
        "gate: answerable wrongly handed off": pct(sum(r["gate_handoff"] for r in ans), len(ans)),
        "retrieval p50": f"{statistics.median(r['retrieve_ms'] for r in results):.0f} ms",
    }
    if retrieval_only:
        return s
    totals = sorted(r["total_ms"] for r in results)
    s.update({
        "answer accuracy (facts present)": pct(sum(r["facts_ok"] for r in ans), len(ans)),
        "cited a correct page": pct(sum(r["cited_gold"] for r in ans), len(ans)),
        "unanswerable handed off": pct(sum(r["handoff"] for r in una), len(una)),
        "answerable wrongly handed off": pct(sum(r["handoff"] for r in ans), len(ans)),
        "end-to-end p50": f"{statistics.median(totals) / 1000:.1f} s",
        "end-to-end p95": f"{totals[min(len(totals) - 1, int(len(totals) * 0.95))] / 1000:.1f} s",
    })
    errors = sum("error" in r for r in results)
    if errors:
        s["LLM errors (counted as misses)"] = str(errors)
    return s


def evaluate(
    conn: psycopg.Connection, items: list[dict], retrieval_only: bool, out: Path | None, resume: bool = False
) -> dict:
    missing = check_gold_pages(conn, items)
    for m in missing:
        print(f"warning: gold page not in index: {m}")

    saved = {}
    if resume and out and out.exists():
        saved = {r["id"]: r for r in json.loads(out.read_text())["results"] if "error" not in r}
        print(f"resuming: {len(saved)} questions already scored in {out}")

    results = []
    for i, item in enumerate(items, 1):
        r = saved.get(item["id"]) or run_item(conn, item, retrieval_only)
        results.append(r)
        print(f"[{i}/{len(items)}] {_status(r, retrieval_only)}  {item['question'][:70]}")
        if out:
            _save(out, results, None, retrieval_only)  # after every question, so a crash loses nothing

    summary = summarize(results, retrieval_only)
    print()
    width = max(map(len, summary))
    for k, v in summary.items():
        print(f"{k:<{width}}  {v}")
    if out:
        _save(out, results, summary, retrieval_only)
        print(f"\nsaved {out}")
    return {"summary": summary, "results": results}


def _save(out: Path, results: list[dict], summary: dict | None, retrieval_only: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "model": None if retrieval_only else config.LLM_MODEL,
        "embed_model": config.EMBED_MODEL,
        "rerank": config.RERANK,
        "min_score": min_score(),
        "summary": summary,
        "results": results,
    }, indent=2))


def _status(r: dict, retrieval_only: bool) -> str:
    if not r["answerable"]:
        handed = r["gate_handoff"] if retrieval_only else r["handoff"]
        return "ok  " if handed else "MISS"
    if retrieval_only:
        return f"#{r['gold_rank']}  " if r["gold_rank"] else "MISS"
    return "ok  " if r["facts_ok"] else "MISS"
