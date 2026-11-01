"""A help center built from a folder of Markdown files: one file per page, `# Title` first.

`import_markdown` turns the folder into the same page records the crawler writes, so
ingest, search and citations work unchanged. The API serves the pages at /help/<slug>,
which gives every citation a real page to open, with heading anchors for each section.
"""

import json
import re
from functools import cache
from html import escape
from pathlib import Path

import markdown

from askdocs import config
from askdocs.chunk import slugify
from askdocs.crawl import page_path

_SLUG = re.compile(r"^[a-z0-9-]+$")
_HEADING = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.M)


def read_page(path: Path) -> dict:
    """Split a Markdown file into its title (the first `# ` line) and body."""
    text = path.read_text()
    first, _, body = text.partition("\n")
    if not first.startswith("# "):
        raise ValueError(f"{path.name}: the first line must be '# Title'")
    return {"slug": path.stem, "title": first[2:].strip(), "markdown": body.strip()}


def import_markdown(source: Path, base_url: str, pages_dir: Path) -> int:
    pages_dir.mkdir(parents=True, exist_ok=True)
    for old in pages_dir.glob("*.json"):
        old.unlink()  # the folder is the source of truth: removed files leave the index
    count = 0
    for path in sorted(source.glob("*.md")):
        page = read_page(path)
        url = base_url.rstrip("/") + "/" + page["slug"]
        record = {
            "url": url,
            "title": page["title"],
            "markdown": page["markdown"],
            "anchors": sorted({slugify(h) for h in _HEADING.findall(page["markdown"])}),
        }
        page_path(pages_dir, url).write_text(json.dumps(record, ensure_ascii=False))
        count += 1
    return count


@cache
def pages() -> dict[str, dict]:
    return {p.stem: read_page(p) for p in sorted(config.HELP_DIR.glob("*.md"))}


def render_html(md: str) -> str:
    # Heading ids use the same slugify as chunking, so citation anchors land on the section.
    return markdown.markdown(
        md,
        extensions=["tables", "toc"],
        extension_configs={"toc": {"slugify": lambda value, _sep: slugify(value)}},
    )


def page_html(slug: str) -> str | None:
    if not _SLUG.match(slug) or slug not in pages():
        return None
    page = pages()[slug]
    body = f'<p class="crumb"><a href="/help">Help center</a></p><h1>{escape(page["title"])}</h1>{render_html(page["markdown"])}'
    return _layout(page["title"], body)


def index_html() -> str:
    items = "".join(
        f'<li><a href="/help/{slug}">{escape(p["title"])}</a></li>'
        for slug, p in sorted(pages().items(), key=lambda kv: kv[1]["title"])
    )
    body = (f"<h1>{escape(config.PRODUCT_NAME)} Help Center</h1>"
            "<p>Shipping, returns, sizing, care and everything else. Or ask the assistant in the corner.</p>"
            f'<ul class="pages">{items}</ul>')
    return _layout("Help Center", body)


def _layout(title: str, body: str) -> str:
    name = escape(config.PRODUCT_NAME)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · {name}</title>
<style>
  :root {{ --bg:#fbfaf7; --fg:#1d2420; --muted:#5f6b63; --line:#e3e0d8; --accent:#2f6b4f; --card:#fff; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#121614; --fg:#e8ece9; --muted:#a3ada6; --line:#2a312d; --accent:#7cc4a0; --card:#1a1f1c; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .banner {{ background:var(--accent); color:#fff; text-align:center; font-size:13px; padding:6px 16px; }}
  @media (prefers-color-scheme: dark) {{ .banner {{ color:#0d1a13; }} }}
  header {{ border-bottom:1px solid var(--line); background:var(--card); }}
  header div {{ max-width:780px; margin:0 auto; padding:14px 16px; display:flex; justify-content:space-between; align-items:center; }}
  header a {{ color:var(--fg); text-decoration:none; font-weight:700; letter-spacing:.02em; }}
  header nav a {{ font-weight:400; color:var(--muted); margin-left:16px; font-size:14px; }}
  main {{ max-width:780px; margin:0 auto; padding:32px 16px 120px; }}
  h1 {{ font-size:clamp(26px,4vw,34px); line-height:1.2; margin:0 0 16px; }}
  h2 {{ font-size:20px; margin:32px 0 8px; }} h3 {{ font-size:17px; margin:24px 0 6px; }}
  a {{ color:var(--accent); }}
  .crumb {{ font-size:14px; margin:0 0 8px; }}
  table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:15px; display:block; overflow-x:auto; }}
  th, td {{ border:1px solid var(--line); padding:8px 10px; text-align:left; }}
  th {{ background:var(--card); }}
  .pages {{ columns:2 260px; padding-left:18px; }} .pages li {{ margin-bottom:6px; break-inside:avoid; }}
  :target {{ scroll-margin-top:16px; background:color-mix(in srgb, var(--accent) 14%, transparent); border-radius:4px; }}
</style></head>
<body>
<div class="banner">{name} is a fictional store made up for this chatbot demo.</div>
<header><div><a href="/help">{name}</a><nav><a href="/help">Help center</a><a href="/">About this demo</a></nav></div></header>
<main>{body}</main>
<script src="/widget.js" defer data-title="{name} support" data-color="#2f6b4f"
        data-greeting="Hi! I can help with orders, shipping, returns, sizing and gear care. What do you need?"></script>
</body></html>"""
