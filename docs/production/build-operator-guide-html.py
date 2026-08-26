"""Build a single self-contained HTML copy of the operator guide.

    python docs/production/build-operator-guide-html.py

The output is one file with the screenshots inlined as data URIs, so it can be
emailed, copied onto a USB stick, or opened offline by someone who will never
see this repository. That matters for the usability test: the participant gets
the guide and nothing else.

Regenerate this whenever `panduan-operator.md` changes — the HTML is a copy,
and a stale copy is worse than none, because the reader has no way to tell.
"""

import base64
import re
import sys
from pathlib import Path

from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "panduan-operator.md"
OUTPUT = HERE / "panduan-operator.html"

# Matches the application's own palette so the guide does not look like a
# different product from the screens it describes.
STYLE = """
:root {
  --ink: #10202b; --muted: #5b6b76; --line: #dde5ea;
  --bg: #ffffff; --panel: #f4f7f9; --accent: #0f5c70; --warn: #8a5a00;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 3rem 1.5rem 6rem; background: var(--bg); color: var(--ink);
  font: 16px/1.7 "Segoe UI", system-ui, -apple-system, sans-serif;
}
main { max-width: 46rem; margin: 0 auto; }
h1 { font-size: 2rem; line-height: 1.25; margin: 0 0 .5rem; }
h2 {
  font-size: 1.35rem; margin: 3rem 0 .75rem;
  padding-top: 1.25rem; border-top: 1px solid var(--line);
}
h1 + p { color: var(--muted); }
a { color: var(--accent); }
code {
  background: var(--panel); padding: .12em .38em; border-radius: 4px;
  font: .9em/1.5 "Cascadia Mono", Consolas, monospace;
}
blockquote {
  margin: 1.5rem 0; padding: 1rem 1.25rem; background: #fff8e8;
  border-left: 4px solid var(--warn); border-radius: 0 6px 6px 0;
}
blockquote p { margin: .35rem 0; }
table { border-collapse: collapse; width: 100%; margin: 1.25rem 0; font-size: .95rem; }
th, td {
  border: 1px solid var(--line); padding: .55rem .7rem;
  text-align: left; vertical-align: top;
}
th { background: var(--panel); font-weight: 600; }
img {
  max-width: 100%; height: auto; display: block; margin: 1.5rem 0;
  border: 1px solid var(--line); border-radius: 8px;
}
hr { border: 0; border-top: 1px solid var(--line); margin: 2.5rem 0; }
ol, ul { padding-left: 1.35rem; }
li { margin: .3rem 0; }
/* Printable, because some operators will want it on paper next to the screen. */
@media print {
  body { padding: 0; font-size: 11pt; }
  h2 { page-break-after: avoid; }
  img, table, blockquote { page-break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}
"""


def slugify(text: str) -> str:
    """GitHub's heading-anchor rules, which is what the guide's own contents assume."""
    slug = re.sub(r"<[^>]+>", "", text).strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    return re.sub(r"[\s]+", "-", slug)


def add_heading_ids(html: str) -> tuple[str, int]:
    """Give every heading an id.

    Without this the table of contents is eight dead links: markdown-it emits
    bare <h2> tags, while the contents list was written against GitHub, which
    generates anchors automatically.
    """
    added = 0

    def swap(match: re.Match[str]) -> str:
        nonlocal added
        level, inner = match.group(1), match.group(2)
        added += 1
        return f'<h{level} id="{slugify(inner)}">{inner}</h{level}>'

    return re.sub(r"<h([1-6])>(.*?)</h\1>", swap, html, flags=re.DOTALL), added


def strip_repository_links(html: str) -> str:
    """Unlink documents the reader will not have.

    The guide points at the recovery runbook, which is deliberately not the
    operator's job and will not travel with this file. A dead link invites a
    click that fails; the sentence reads fine as plain text.
    """
    return re.sub(r'<a href="[^"]+\.md(#[^"]*)?">(.*?)</a>', r'\2', html, flags=re.DOTALL)


def inline_images(html: str, base: Path) -> tuple[str, int]:
    """Replace every <img src="images/..."> with a data URI."""
    embedded = 0

    def swap(match: re.Match[str]) -> str:
        nonlocal embedded
        source = match.group(1)
        path = base / source
        if not path.is_file():
            raise SystemExit(f"missing image referenced by the guide: {source}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        embedded += 1
        return f'src="data:image/png;base64,{encoded}"'

    return re.sub(r'src="([^"]+\.png)"', swap, html), embedded


def main() -> int:
    markdown = SOURCE.read_text(encoding="utf-8")
    body = MarkdownIt("commonmark").enable("table").render(markdown)
    body, headings = add_heading_ids(body)
    body = strip_repository_links(body)
    body, embedded = inline_images(body, SOURCE.parent)

    dangling = re.findall(r'href="#([^"]+)"', body)
    anchors = set(re.findall(r'id="([^"]+)"', body))
    broken = sorted(set(dangling) - anchors)
    if broken:
        raise SystemExit(f"table of contents points at headings that do not exist: {broken}")
    remaining = re.findall(r'href="([^#"][^"]*)"', body)
    if remaining:
        raise SystemExit(f"links to files the reader will not have: {sorted(set(remaining))}")

    if 'src="images/' in body or "images/" in body and embedded == 0:
        raise SystemExit("an image reference survived un-inlined; the file would not be portable")

    OUTPUT.write_text(
        "<!doctype html>\n"
        '<html lang="id">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Panduan Operator — Perencana Operasi Harian</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n",
        encoding="utf-8",
    )
    size = OUTPUT.stat().st_size
    print(
        f"{OUTPUT.name}: {size // 1024} KB, {embedded} screenshots embedded, "
        f"{headings} headings anchored, {len(set(dangling))} contents links verified"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
