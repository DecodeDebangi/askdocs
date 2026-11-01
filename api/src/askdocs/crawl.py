"""Fetch every docs page listed in a sitemap and save its main content as Markdown.

Pages are cached in data/pages/, so re-running only fetches pages that are missing.
"""

import asyncio
import hashlib
import html as html_lib
import json
import re
from pathlib import Path

import httpx
import lxml.html
import trafilatura

USER_AGENT = "askdocs-crawler/0.1 (+https://github.com/DecodeDebangi/askdocs)"

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_HEADING_ID = re.compile(r"<h[1-4][^>]*\sid=\"([^\"]+)\"", re.I)


def page_path(pages_dir: Path, url: str) -> Path:
    return pages_dir / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")


async def sitemap_urls(client: httpx.AsyncClient, sitemap_url: str, prefix: str) -> list[str]:
    resp = await client.get(sitemap_url)
    resp.raise_for_status()
    urls = [u for u in _LOC.findall(resp.text) if u.startswith(prefix)]
    return sorted(set(urls))


def flatten_code_blocks(tree: lxml.html.HtmlElement) -> None:
    """Supabase renders each code line as its own <div>, which extraction joins into one
    line. Rebuild every <pre> as a single <code> with real newlines."""
    for pre in tree.iter("pre"):
        lines = pre.find_class("code-line-content")
        if not lines:
            continue
        text = "\n".join(line.text_content() for line in lines)
        for child in list(pre):
            pre.remove(child)
        code = lxml.html.Element("code")
        code.text = text
        pre.append(code)


def extract_page(url: str, html: str) -> dict | None:
    tree = lxml.html.fromstring(html)
    flatten_code_blocks(tree)
    markdown = trafilatura.extract(
        tree,
        url=url,
        output_format="markdown",
        include_formatting=True,
        include_tables=True,
        include_links=False,
        include_comments=False,
        favor_recall=True,
    )
    if not markdown:
        return None
    title_match = _TITLE.search(html)
    title = html_lib.unescape(title_match.group(1).strip()) if title_match else url
    title = re.sub(r"\s*\|\s*Supabase Docs\s*$", "", title)
    return {
        "url": url,
        "title": title,
        "markdown": markdown,
        # Heading ids let citations link straight to the section, e.g. page#usage.
        "anchors": sorted(set(_HEADING_ID.findall(html))),
    }


async def _fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str, out: Path) -> str:
    async with sem:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return f"error {url}: {e}"
    page = extract_page(url, resp.text)
    if page is None:
        return f"empty {url}"
    out.write_text(json.dumps(page, ensure_ascii=False))
    return "ok"


async def crawl(sitemap_url: str, prefix: str, pages_dir: Path, limit: int | None, concurrency: int) -> None:
    pages_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        urls = await sitemap_urls(client, sitemap_url, prefix)
        if limit:
            urls = urls[:limit]
        todo = [u for u in urls if not page_path(pages_dir, u).exists()]
        print(f"{len(urls)} pages in sitemap, {len(urls) - len(todo)} cached, fetching {len(todo)}")

        sem = asyncio.Semaphore(concurrency)
        results = await asyncio.gather(*(_fetch(client, sem, u, page_path(pages_dir, u)) for u in todo))

    problems = [r for r in results if r != "ok"]
    for p in problems:
        print(p)
    print(f"done: {len(results) - len(problems)} saved, {len(problems)} skipped")
