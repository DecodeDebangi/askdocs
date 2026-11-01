"""A help center built from a folder of Markdown files: one file per page, `# Title` first.

`import_markdown` turns the folder into the same page records the crawler writes, so
ingest, search and citations work unchanged. The API serves the pages as a help center
(home, topic pages, articles) with heading anchors that match citation links.

Branding, topics, navigation and the assistant's look come from `_site.json` in the folder.
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
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
FONTS = "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=Inter:wght@400;500;600;700&display=swap"

ICONS = {
    "bag": '<path d="M6 7h12l-1 13H7L6 7z"/><path d="M9 7a3 3 0 0 1 6 0"/>',
    "truck": '<path d="M3 6h11v9H3z"/><path d="M14 9h4l3 3v3h-7"/><circle cx="7" cy="17" r="1.8"/><circle cx="17" cy="17" r="1.8"/>',
    "return": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "ruler": '<rect x="3" y="8" width="18" height="8" rx="1.5"/><path d="M7 8v3M11 8v4M15 8v3"/>',
    "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "shield": '<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3z"/><path d="m9 12 2 2 4-4"/>',
    "gift": '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M5 12v8h14v-8M12 8v12"/><path d="M12 8S10.5 4 8.5 4a2 2 0 0 0 0 4M12 8s1.5-4 3.5-4a2 2 0 0 1 0 4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "pin": '<path d="M12 21s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    "phone": '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
}
LOGO = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 1.5 6.2 9.3h3L5 15.2h5.2V22h3.6v-6.8H19l-4.2-5.9h3z"/></svg>'


def icon(name: str) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


# ---------- Content ----------

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


@cache
def site() -> dict:
    """Branding and topics from _site.json; without it, one topic holding every page."""
    path = config.HELP_DIR / "_site.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"brand": config.PRODUCT_NAME, "tagline": "", "assistant": {}, "nav": [], "popular": [],
            "categories": [{"id": "all", "name": "All articles", "icon": "bag", "description": "",
                            "pages": sorted(pages())}]}


def category_of(slug: str) -> dict | None:
    return next((c for c in site()["categories"] if slug in c["pages"]), None)


def render_html(md: str) -> str:
    # Heading ids use the same slugify as chunking, so citation anchors land on the section.
    return markdown.markdown(
        md,
        extensions=["tables", "toc"],
        extension_configs={"toc": {"slugify": lambda value, _sep: slugify(value)}},
    )


def _search_index() -> str:
    entries = []
    for slug, p in pages().items():
        cat = category_of(slug)
        text = (p["title"] + " " + " ".join(_HEADING.findall(p["markdown"]))).lower()
        entries.append({"slug": slug, "title": p["title"], "category": cat["name"] if cat else "", "text": text})
    # Escape "</" so page text can never close the <script> tag early.
    return json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")


# ---------- Pages ----------

def _search_box(hint: bool) -> str:
    hint_html = '<p class="hint">Type a question and press Enter to ask our assistant.</p>' if hint else ""
    return f"""<div class="search">
  <form role="search">
    {icon("search")}
    <label class="sr-only" for="q">Search the help center</label>
    <input id="q" type="search" autocomplete="off" placeholder="Search articles or ask a question">
    <button type="submit">{icon("chat")}<span>Ask</span></button>
  </form>
  <div class="results" role="listbox"></div>
  {hint_html}
</div>"""


def home_html() -> str:
    s = site()
    cards = "".join(
        f'<a class="card" href="/help/topic/{c["id"]}"><span class="icon">{icon(c["icon"])}</span>'
        f'<span><h3>{escape(c["name"])}</h3><p>{escape(c["description"])}</p>'
        f'<div class="count">{len(c["pages"])} articles</div></span></a>'
        for c in s["categories"]
    )
    popular = "".join(
        f'<li><a href="/help/{slug}">{escape(pages()[slug]["title"])}</a></li>' for slug in s["popular"] if slug in pages()
    )
    body = f"""
<section class="hero"><div class="wrap">
  <h1>How can we help?</h1>
  <p>Answers about orders, shipping, returns, sizing and caring for your gear.</p>
  {_search_box(hint=True)}
</div></section>
{_showcase()}
<section class="section"><div class="wrap">
  <h2>Browse by topic</h2>
  <div class="grid">{cards}</div>
</div></section>
<section class="section" style="padding-top:0"><div class="wrap">
  <h2>Popular articles</h2>
  <ul class="list">{popular}</ul>
</div></section>
{_contact_band()}"""
    return _layout("Help Center", body, current="home")


def _showcase() -> str:
    """Curated questions that show precision: each card says what the help center says and
    links to that exact section, so visitors can check the assistant's answer themselves."""
    sc = site().get("showcase")
    if not sc:
        return ""
    groups = []
    for g in sc["groups"]:
        cards = []
        for it in g["items"]:
            slug, _, anchor = it.get("source", "").partition("#")
            check = ""
            if slug in pages():
                href = f"/help/{slug}" + (f"#{anchor}" if anchor else "")
                check = f'<a class="check" href="{href}">Check the source: {escape(pages()[slug]["title"])} →</a>'
            cards.append(
                f'<div class="try"><button type="button" class="try-q" data-ask="{escape(it["q"])}">'
                f'<span>{escape(it["q"])}</span>{icon("chat")}</button>'
                f'<p class="expect"><b>{"Help center says" if check else "Expected"}</b>{escape(it["expect"])}</p>{check}</div>')
        groups.append(f'<div class="try-group"><h3><span class="icon">{icon(g["icon"])}</span>{escape(g["name"])}</h3>{"".join(cards)}</div>')
    return f"""<section class="section showcase"><div class="wrap">
  <h2>{escape(sc["title"])}</h2>
  <p class="lede">{escape(sc["intro"])}</p>
  <div class="try-grid">{"".join(groups)}</div>
</div></section>"""


def demo_questions_html() -> str:
    """The showcase as a compact question list for the product page's live demo. Each button
    carries what the help center says, so the page can set it beside the answer."""
    sc = site().get("showcase")
    if not sc:
        return ""
    out = []
    for g in sc["groups"]:
        items = []
        for it in g["items"]:
            slug, _, anchor = it.get("source", "").partition("#")
            src = ""
            if slug in pages():
                href = f"/help/{slug}" + (f"#{anchor}" if anchor else "")
                src = f' data-href="{href}" data-title="{escape(pages()[slug]["title"])}"'
            items.append(f'<li><button type="button" class="dq" data-ask="{escape(it["q"])}" data-expect="{escape(it["expect"])}"{src}>'
                         f'{escape(it["q"])}</button></li>')
        out.append(f'<div class="dq-group"><h3>{escape(g["name"])}</h3><ul>{"".join(items)}</ul></div>')
    return "".join(out)


def product_html(template: str) -> str:
    """The product page, with the live demo's questions and assistant settings filled in."""
    a = site().get("assistant", {})
    return (template.replace("<!--DEMO-QUESTIONS-->", demo_questions_html())
            .replace("{{ASSISTANT_TITLE}}", escape(a.get("title", "Assistant")))
            .replace("{{ASSISTANT_SUBTITLE}}", escape(a.get("subtitle", "")))
            .replace("{{ASSISTANT_COLOR}}", escape(a.get("color", "#2d5a45")))
            .replace("{{ASSISTANT_GREETING}}", escape(a.get("greeting", ""))))


def topic_html(topic_id: str) -> str | None:
    cat = next((c for c in site()["categories"] if c["id"] == topic_id), None)
    if not cat:
        return None
    items = "".join(f'<li><a href="/help/{slug}">{escape(pages()[slug]["title"])}</a></li>' for slug in cat["pages"])
    body = f"""<div class="wrap">
  <nav class="crumbs" aria-label="Breadcrumb"><a href="/help">Help Center</a><span>/</span><span>{escape(cat["name"])}</span></nav>
  <div class="page-head"><h1>{escape(cat["name"])}</h1><p>{escape(cat["description"])}</p></div>
  <div class="section" style="padding-top:24px"><ul class="list">{items}</ul></div>
</div>
{_contact_band()}"""
    return _layout(cat["name"], body)


def page_html(slug: str) -> str | None:
    if not _SLUG.match(slug) or slug not in pages():
        return None
    page = pages()[slug]
    cat = category_of(slug)
    h2s = _H2.findall(page["markdown"])
    toc = ""
    if len(h2s) >= 3:
        toc = '<nav class="toc" aria-label="On this page"><b>On this page</b><ol>' + "".join(
            f'<li><a href="#{slugify(h)}">{escape(h)}</a></li>' for h in h2s) + "</ol></nav>"
    crumb_cat = f'<a href="/help/topic/{cat["id"]}">{escape(cat["name"])}</a><span>/</span>' if cat else ""
    related = ""
    if cat:
        related = '<div class="side-card"><h4>' + escape(cat["name"]) + "</h4><ul>" + "".join(
            f'<li><a href="/help/{s}"{" aria-current=page" if s == slug else ""}>{escape(pages()[s]["title"])}</a></li>'
            for s in cat["pages"]) + "</ul></div>"
    body = f"""<div class="wrap">
  <nav class="crumbs" aria-label="Breadcrumb"><a href="/help">Help Center</a><span>/</span>{crumb_cat}<span>{escape(page["title"])}</span></nav>
  <div class="article-layout">
    <article class="article">
      <h1>{escape(page["title"])}</h1>
      {toc}
      <div class="prose">{render_html(page["markdown"])}</div>
      <div class="help-box">
        <div><h3>Still have a question?</h3><p>Our assistant answers from this help center in seconds.</p></div>
        <div class="actions"><a class="btn btn-primary" href="#" data-ask>{icon("chat")}Ask the assistant</a>
        <a class="btn btn-ghost" href="/help/contact-us">Contact us</a></div>
      </div>
    </article>
    <aside class="sidebar">
      <div class="side-card"><h4>Search</h4>{_search_box(hint=False)}</div>
      {related}
    </aside>
  </div>
</div>"""
    return _layout(page["title"], body)


def _contact_band() -> str:
    return f"""<section class="section contact-band"><div class="wrap">
  <h2>Still need help?</h2>
  <div class="contact">
    <div><h3>Ask our assistant</h3><p>Instant answers from this help center, any time.</p><p class="big"><a href="#" data-ask>Start a chat →</a></p></div>
    <div><h3>Call us</h3><p>Monday to Friday, 6 am–6 pm PT</p><p class="big">1-800-555-0142</p></div>
    <div><h3>Email us</h3><p>We reply within 1 business day</p><p class="big">help@fernhollow.example</p></div>
  </div>
</div></section>"""


def _layout(title: str, body: str, current: str = "") -> str:
    s = site()
    brand = escape(s["brand"])
    a = s.get("assistant", {})
    nav = "".join(f'<a href="/help/{n["slug"]}">{escape(n["label"])}</a>' for n in s["nav"])
    topics = "".join(f'<li><a href="/help/topic/{c["id"]}">{escape(c["name"])}</a></li>' for c in s["categories"][:6])
    suggestions = escape("|".join(a.get("suggestions", [])))
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · {brand} Help</title>
<meta name="description" content="{brand} Help Center: {escape(s.get("tagline", ""))}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="/assets/site.css">
</head><body>
<div class="demo-bar"><div class="wrap"><span><b>Live demo.</b> {brand} is a fictional store; the AI assistant is the product.</span><a href="/">How it works →</a></div></div>
<header class="site-header"><div class="wrap">
  <a class="logo" href="/help" aria-label="{brand} Help Center home">{LOGO}<b>{brand.upper()}</b><span>Help Center</span></a>
  <nav class="site-nav" aria-label="Help">{nav}</nav>
</div></header>
<main>{body}</main>
<footer class="site-footer"><div class="wrap">
  <div class="footer-grid">
    <div><a class="logo" href="/help">{LOGO}<b>{brand.upper()}</b></a><p style="margin:12px 0 0;max-width:320px">{escape(s.get("tagline", ""))}</p></div>
    <div><h4>Help topics</h4><ul>{topics}</ul></div>
    <div><h4>Contact</h4><ul><li><a href="#" data-ask>Chat with our assistant</a></li><li>1-800-555-0142</li><li>help@fernhollow.example</li><li><a href="/help/store-locations">Store locations</a></li></ul></div>
  </div>
  <div class="footer-note"><span>{brand} is a fictional brand. This help center and its AI assistant are a working demo.</span><a href="/">About the assistant</a></div>
</div></footer>
<script type="application/json" id="search-index">{_search_index()}</script>
<script src="/assets/site.js" defer></script>
<script src="/widget.js" defer
  data-title="{escape(a.get("title", brand + " support"))}"
  data-subtitle="{escape(a.get("subtitle", ""))}"
  data-color="{escape(a.get("color", "#2d5a45"))}"
  data-greeting="{escape(a.get("greeting", ""))}"
  data-suggestions="{suggestions}"
  data-label="Ask a question"></script>
</body></html>"""
