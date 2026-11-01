import json

from askdocs import helpcenter
from askdocs.chunk import chunk_page


def write(dir_, name, text):
    (dir_ / name).write_text(text)


def test_import_markdown_writes_pages_with_anchors(tmp_path):
    src, out = tmp_path / "src", tmp_path / "pages"
    src.mkdir()
    write(src, "returns.md", "# Return policy\n\nIntro.\n\n## Return window\n\n30 days.\n\n## Final sale items\n\nGift cards.\n")
    write(src, "contact.md", "# Contact us\n\nCall us.\n")
    (out).mkdir()
    (out / "stale.json").write_text("{}")

    assert helpcenter.import_markdown(src, "https://shop.example/help/", out) == 2
    records = {r["url"]: r for r in (json.loads(p.read_text()) for p in out.glob("*.json"))}
    assert set(records) == {"https://shop.example/help/returns", "https://shop.example/help/contact"}
    page = records["https://shop.example/help/returns"]
    assert page["title"] == "Return policy" and not page["markdown"].startswith("#")
    assert page["anchors"] == ["final-sale-items", "return-window"]
    chunk = [c for c in chunk_page(page, min_chars=1) if c.section == "Return window"][0]
    assert chunk.anchor == "return-window"


def test_rendered_heading_ids_match_citation_anchors():
    html = helpcenter.render_html("## Duties and taxes\n\ntext\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert 'id="duties-and-taxes"' in html and "<table>" in html


def test_page_html_rejects_unknown_and_unsafe_slugs():
    assert helpcenter.page_html("../../etc/passwd") is None
    assert helpcenter.page_html("no-such-page") is None
    assert "Return policy" in helpcenter.page_html("return-policy")


def test_showcase_source_links_point_at_real_sections():
    for group in helpcenter.site()["showcase"]["groups"]:
        for item in group["items"]:
            if "source" not in item:
                continue
            slug, _, anchor = item["source"].partition("#")
            html = helpcenter.page_html(slug)
            assert html is not None, item["source"]
            assert not anchor or f'id="{anchor}"' in html, item["source"]


def test_product_page_fills_every_placeholder():
    from askdocs.api import STATIC

    html = helpcenter.product_html((STATIC / "about.html").read_text())
    assert "{{" not in html and "<!--DEMO-QUESTIONS-->" not in html
    assert 'data-target="#chat"' in html
    assert html.count('class="dq"') == sum(len(g["items"]) for g in helpcenter.site()["showcase"]["groups"])
