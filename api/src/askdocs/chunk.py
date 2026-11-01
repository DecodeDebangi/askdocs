"""Split a page into chunks along its headings.

Each chunk stays inside one section, so a citation can point to that section.
Sections longer than max_chars are split on paragraph boundaries; code blocks
are never cut in half.
"""

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Chunk:
    url: str
    title: str
    section: str | None
    anchor: str | None
    ord: int
    content: str

    @property
    def embed_text(self) -> str:
        """Content prefixed with where it comes from, which improves retrieval."""
        where = self.title if not self.section else f"{self.title} > {self.section}"
        return f"{where}\n\n{self.content}"


def slugify(heading: str) -> str:
    s = re.sub(r"[`*_\[\]()]", "", heading.lower())
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    return re.sub(r"[\s-]+", "-", s).strip("-")


def split_sections(markdown: str) -> list[tuple[str | None, str]]:
    """Return (heading, body) pairs. Text before the first heading has heading None."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    in_code = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_code = not in_code
        m = None if in_code else _HEADING.match(line)
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    return [(h, "\n".join(body).strip()) for h, body in sections if "\n".join(body).strip()]


def split_blocks(text: str) -> list[str]:
    """Split on blank lines, keeping each fenced code block as one block."""
    blocks, current, in_code = [], [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_code = not in_code
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def pack(blocks: list[str], max_chars: int) -> list[str]:
    """Greedily join blocks into pieces of at most max_chars (a single larger block stays whole)."""
    pieces, current = [], ""
    for block in blocks:
        if current and len(current) + 2 + len(block) > max_chars:
            pieces.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        pieces.append(current)
    return pieces


def chunk_page(page: dict, max_chars: int = 1800, min_chars: int = 40) -> list[Chunk]:
    anchors = set(page.get("anchors", []))
    chunks: list[Chunk] = []
    for heading, body in split_sections(page["markdown"]):
        slug = slugify(heading) if heading else None
        anchor = slug if slug in anchors else None
        for piece in pack(split_blocks(body), max_chars):
            if len(piece) < min_chars:
                continue
            chunks.append(Chunk(page["url"], page["title"], heading, anchor, len(chunks), piece))
    return chunks
