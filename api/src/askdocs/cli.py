import argparse
import asyncio
import json
import time

from askdocs import config


def cmd_crawl(args: argparse.Namespace) -> None:
    from askdocs.crawl import crawl

    asyncio.run(crawl(args.sitemap, args.prefix, config.PAGES_DIR, args.limit, args.concurrency))


def cmd_import_markdown(args: argparse.Namespace) -> None:
    from pathlib import Path

    from askdocs.helpcenter import import_markdown

    n = import_markdown(Path(args.source), args.base_url, config.PAGES_DIR)
    print(f"imported {n} pages into {config.PAGES_DIR}, cited as {args.base_url.rstrip('/')}/<slug>")


def cmd_ingest(args: argparse.Namespace) -> None:
    from askdocs import db
    from askdocs.chunk import chunk_page
    from askdocs.embed import embed_passages

    pages = [json.loads(p.read_text()) for p in sorted(config.PAGES_DIR.glob("*.json"))]
    if not pages:
        raise SystemExit("No pages found. Run `askdocs crawl` first.")

    conn = db.connect()
    db.init_schema(conn, reset=args.reset)
    started = time.perf_counter()
    updated = unchanged = total_chunks = 0

    # Embed pages in groups of ~200 chunks: few API calls, and each group is saved
    # before the next, so a quota stop loses at most one group. Re-running resumes.
    group: list[list] = []

    def flush() -> None:
        nonlocal updated
        if not group:
            return
        vectors = embed_passages([c.embed_text for chunks in group for c in chunks])
        offset = 0
        for chunks in group:
            db.replace_page(conn, chunks, vectors[offset:offset + len(chunks)])
            offset += len(chunks)
        updated += len(group)
        print(f"  {updated} pages embedded...")
        group.clear()

    for page in pages:
        chunks = chunk_page(page)
        if not chunks:
            continue
        total_chunks += len(chunks)
        if not args.force and db.stored_hash(conn, page["url"]) == db.page_hash(chunks):
            unchanged += 1
            continue
        group.append(chunks)
        if sum(map(len, group)) >= 200:
            flush()
    flush()
    removed = db.delete_missing(conn, {p["url"] for p in pages})
    print(
        f"{len(pages)} pages, {total_chunks} chunks: {updated} updated, {unchanged} unchanged, "
        f"{removed} removed in {time.perf_counter() - started:.1f}s"
    )


def cmd_search(args: argparse.Namespace) -> None:
    from askdocs import db
    from askdocs.search import search

    conn = db.connect()
    started = time.perf_counter()
    hits = search(conn, args.query, args.k)
    print(f"{len(hits)} results in {(time.perf_counter() - started) * 1000:.0f} ms\n")
    for i, h in enumerate(hits, 1):
        ranks = f"vec #{h.vec_rank or '-'}  kw #{h.kw_rank or '-'}  sim {h.similarity:.2f}"
        print(f"{i}. {h.title}{' > ' + h.section if h.section else ''}   [{ranks}]")
        print(f"   {h.link}")
        print("   " + h.content[:200].replace("\n", " ") + ("..." if len(h.content) > 200 else ""))
        print()


def cmd_eval(args: argparse.Namespace) -> None:
    from pathlib import Path

    from askdocs import db
    from askdocs.evaluate import evaluate, load_set

    items = load_set(Path(args.set))[: args.limit]
    evaluate(db.connect(), items, args.retrieval_only, Path(args.out) if args.out else None, args.resume)


def main() -> None:
    parser = argparse.ArgumentParser(prog="askdocs")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("crawl", help="fetch docs pages from a sitemap into data/pages/")
    p.add_argument("--sitemap", default=config.SITEMAP_URL)
    p.add_argument("--prefix", default=config.URL_PREFIX, help="only crawl URLs starting with this")
    p.add_argument("--limit", type=int, help="crawl at most N pages (for a quick test)")
    p.add_argument("--concurrency", type=int, default=6)
    p.set_defaults(func=cmd_crawl)

    p = sub.add_parser("import-markdown", help="use a folder of Markdown files as the pages (instead of crawling)")
    p.add_argument("source", nargs="?", default=str(config.HELP_DIR))
    p.add_argument("--base-url", default=f"{config.PUBLIC_URL}/help")
    p.set_defaults(func=cmd_import_markdown)

    p = sub.add_parser("ingest", help="chunk, embed and store crawled pages in Postgres")
    p.add_argument("--force", action="store_true", help="re-embed pages even if unchanged")
    p.add_argument("--reset", action="store_true", help="drop and rebuild the index (needed when changing embedding size)")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("search", help="run a hybrid search from the terminal")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("eval", help="score answers against a labelled question set")
    p.add_argument("--set", default="evals/supabase.jsonl")
    p.add_argument("--retrieval-only", action="store_true", help="skip the LLM; score search and the relevance gate")
    p.add_argument("--limit", type=int, help="only the first N questions")
    p.add_argument("--out", help="save per-question results as JSON, e.g. runs/qwen7b.json")
    p.add_argument("--resume", action="store_true", help="reuse results already saved in --out")
    p.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
