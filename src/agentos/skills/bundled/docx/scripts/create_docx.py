"""Create a `.docx` from a declarative JSON spec.

Spec schema:
    {
      "metadata": {"title": "...", "author": "..."},
      "body": [
        {"kind": "heading", "level": 1, "text": "..."},
        {"kind": "paragraph", "text": "...", "style": "Normal"},
        {"kind": "table", "rows": [["..."]]}
      ]
    }

Heading levels are validated against python-docx's 0-9 range: a spec asking
for anything outside it fails with exit code 2 instead of a traceback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from docx import Document

MAX_HEADING_LEVEL = 9


class SpecError(ValueError):
    """A spec value that cannot be rendered into a document."""


def _heading_level(item: dict[str, Any]) -> int:
    """Return *item*'s heading level, or raise `SpecError` if it is unusable.

    python-docx accepts only 0-9, and a model-authored spec asks for `level:
    10` easily enough. Passing the raw integer through aborts the whole run
    with a `ValueError` traceback, which tells the caller nothing about which
    part of the spec was wrong or how to fix it.
    """
    raw = item.get("level", 1)
    try:
        level = int(raw)
    except (TypeError, ValueError):
        raise SpecError(f"heading level must be an integer, got {raw!r}") from None
    if not 0 <= level <= MAX_HEADING_LEVEL:
        raise SpecError(f"heading level must be between 0 and {MAX_HEADING_LEVEL}, got {level}")
    return level


def build(spec: dict[str, Any]) -> Document:
    doc = Document()

    meta = spec.get("metadata", {})
    if isinstance(meta, dict):
        core = doc.core_properties
        if "title" in meta:
            core.title = str(meta["title"])
        if "author" in meta:
            core.author = str(meta["author"])

    for item in spec.get("body", []):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "heading":
            doc.add_heading(str(item.get("text", "")), level=_heading_level(item))
        elif kind == "paragraph":
            style = item.get("style") or "Normal"
            doc.add_paragraph(str(item.get("text", "")), style=style)
        elif kind == "table":
            rows = item.get("rows") or []
            if not rows:
                continue
            ncols = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=ncols)
            for r_idx, row in enumerate(rows):
                for c_idx, value in enumerate(row):
                    table.rows[r_idx].cells[c_idx].text = str(value)
        elif kind == "page_break":
            doc.add_page_break()
    return doc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a .docx from a JSON spec.")
    parser.add_argument("spec", type=Path, help="Path to a JSON spec file")
    parser.add_argument("--out", type=Path, required=True, help="Output .docx path")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.spec.is_file():
        print(f"error: spec {args.spec} not found", file=sys.stderr)
        return 2
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    try:
        doc = build(spec)
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
