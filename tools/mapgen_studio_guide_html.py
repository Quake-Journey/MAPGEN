r"""The Studio's guide as HTML pages beside its Markdown (Fable's brief 10, D1) - to read in a browser, pictures and all.

    python tools/mapgen_studio_guide_html.py

doc/mapgen_studio/MAPGEN_Studio_Guide_RU.md and _EN.md -> .html next to them (the screens/ folder is shared). Only
what the guides use: headings, paragraphs, lists (one level, continued lines), **bold**, `code`, «quotes» as they
are, ![alt](picture) on a line of its own.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "doc" / "mapgen_studio"
STYLE = """body{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;line-height:1.5;
color:#1b1b1f;background:#fafafa}h1{font-size:30px}h2{margin-top:36px;border-bottom:1px solid #ddd;padding-bottom:4px}
h3{margin-top:24px}img{max-width:100%;border:1px solid #ccc;border-radius:6px;margin:8px 0 16px}
code{background:#eee;padding:1px 4px;border-radius:3px}li{margin:3px 0}"""


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def convert(md: str, title: str) -> str:
    body, para, items = [], [], []

    def flush():
        if para:
            body.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            body.append("<ul>" + "".join("<li>" + inline(i) + "</li>" for i in items) + "</ul>")
            items.clear()

    for line in md.splitlines():
        s = line.rstrip()
        img = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", s.strip())
        if not s.strip():
            flush()
        elif img:
            flush()
            body.append(f'<img alt="{html.escape(img.group(1))}" src="{html.escape(img.group(2))}">')
        elif s.startswith("#"):
            flush()
            level = len(s) - len(s.lstrip("#"))
            body.append(f"<h{level}>{inline(s[level:].strip())}</h{level}>")
        elif s.startswith("- "):
            if para:
                flush()
            items.append(s[2:])
        elif items and s.startswith("  "):
            items[-1] += " " + s.strip()
        else:
            if items:
                flush()
            para.append(s.strip())
    flush()
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{STYLE}</style></head><body>\n" + "\n".join(body) + "\n</body></html>\n")


def main() -> int:
    for lang in ("RU", "EN"):
        md = DOC / f"MAPGEN_Studio_Guide_{lang}.md"
        text = md.read_text(encoding="utf-8")
        first = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("# ")), "MAPGEN Studio")
        md.with_suffix(".html").write_text(convert(text, first), encoding="utf-8")
        print(md.with_suffix(".html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
