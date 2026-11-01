from askdocs.chunk import chunk_page, pack, slugify, split_blocks, split_sections

PAGE = {
    "url": "https://example.com/docs/auth",
    "title": "Auth",
    "anchors": ["sign-up", "row-level-security"],
    "markdown": """Intro paragraph that comes before any heading, long enough to keep.

## Sign up

Call `signUp` with an email and password to create a user.

```js
// ## not a heading inside code
const { data } = await supabase.auth.signUp({ email, password })
```

## Row Level Security (RLS)

Policies decide which rows each user can read or write in your tables.

## Unknown section

Short body text that still passes the minimum length check.
""",
}


def test_split_sections_ignores_headings_in_code():
    sections = split_sections(PAGE["markdown"])
    assert [h for h, _ in sections] == [None, "Sign up", "Row Level Security (RLS)", "Unknown section"]
    assert "## not a heading" in sections[1][1]


def test_split_blocks_keeps_code_block_whole():
    text = "para one\n\n```py\nx = 1\n\ny = 2\n```\n\npara two"
    assert split_blocks(text) == ["para one", "```py\nx = 1\n\ny = 2\n```", "para two"]


def test_pack_respects_max_chars():
    assert pack(["a" * 10, "b" * 10, "c" * 10], max_chars=25) == ["a" * 10 + "\n\n" + "b" * 10, "c" * 10]
    assert pack(["x" * 50], max_chars=10) == ["x" * 50]


def test_slugify():
    assert slugify("Row Level Security (RLS)") == "row-level-security-rls"
    assert slugify("Sign up") == "sign-up"


def test_chunk_page_sets_anchor_only_when_page_has_it():
    chunks = chunk_page(PAGE)
    by_section = {c.section: c for c in chunks}
    assert by_section["Sign up"].anchor == "sign-up"
    assert by_section["Row Level Security (RLS)"].anchor is None  # slug not in page ids
    assert by_section[None].anchor is None
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    assert by_section["Sign up"].embed_text.startswith("Auth > Sign up\n\n")
