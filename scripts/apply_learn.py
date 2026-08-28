#!/usr/bin/env python3
"""Append a taught note from a bot comment or repository_dispatch. Stdlib only."""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "context" / "learned.md"
HEADER = "# Learned\n\nNotes the team taught @if-this-ships. Treat these as rules on the next review.\n"
MARK = re.compile(r"<!-- if-this-ships-learn ([A-Za-z0-9+/=]+) -->")


def parse_learn_env(environ: dict[str, str] | None = None) -> dict | None:
    env = environ if environ is not None else os.environ
    raw = (env.get("LEARN_JSON") or "").strip()
    if raw and raw not in ("null", "{}", "[]"):
        data = json.loads(raw)
        if (data.get("lesson") or "").strip():
            return data
    body = env.get("COMMENT_BODY") or ""
    m = MARK.search(body)
    if not m:
        return None
    return json.loads(base64.b64decode(m.group(1)).decode("utf-8"))


def main() -> None:
    data = parse_learn_env()
    if not data:
        return
    lesson = (data.get("lesson") or "").strip()
    if not lesson:
        return
    scope = data.get("scope") or "all"
    bridge = data.get("bridge") or ""
    source = data.get("source") or "teach"
    about = (data.get("about") or "").strip()
    current = PATH.read_text(encoding="utf-8") if PATH.exists() else HEADER
    if lesson in current and source in current:
        return
    if not current.endswith("\n"):
        current += "\n"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scope_line = (
        "**Scope:** all bridges" if scope == "all" else f"**Scope:** only `{bridge}`"
    )
    block = f"\n## {now} — {source}\n{scope_line}\n"
    if about:
        block += f"About: {about}\n"
    block += f"{lesson}\n"
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(current + block, encoding="utf-8")


if __name__ == "__main__":
    main()
