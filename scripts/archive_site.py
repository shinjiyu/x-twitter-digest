#!/usr/bin/env python3
"""Snapshot current site/ into site/archive/<stamp>/ and refresh archive index."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
ARCHIVE = SITE / "archive"


def esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main() -> int:
    index = SITE / "index.html"
    summary = SITE / "tweets_summary.json"
    if not index.is_file():
        print("[ERROR] site/index.html missing", flush=True)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    dest = ARCHIVE / stamp
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(index, dest / "index.html")
    if summary.is_file():
        shutil.copy2(summary, dest / "tweets_summary.json")

    meta = {
        "stamp": stamp,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "hours_window": None,
        "kept_count": None,
    }
    if summary.is_file():
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
            meta["hours_window"] = data.get("hours_window")
            meta["kept_count"] = data.get("kept_count")
            meta["generated_at"] = data.get("generated_at")
        except json.JSONDecodeError:
            pass
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Build archive listing (newest first)
    entries = []
    if ARCHIVE.is_dir():
        for p in sorted(ARCHIVE.iterdir(), reverse=True):
            if not p.is_dir() or p.name == "index.html":
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{4}Z", p.name):
                continue
            mpath = p / "meta.json"
            kept = "?"
            hours = "?"
            if mpath.is_file():
                try:
                    m = json.loads(mpath.read_text(encoding="utf-8"))
                    kept = str(m.get("kept_count", "?"))
                    hours = str(m.get("hours_window", "?"))
                except json.JSONDecodeError:
                    pass
            entries.append((p.name, kept, hours))

    rows = "".join(
        f'<li><a href="{esc(name)}/">{esc(name)}</a>'
        f" · 推文 {esc(kept)} · 窗 {esc(hours)}h</li>\n"
        for name, kept, hours in entries
    )
    listing = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>历史摘要归档</title>
<style>
  body {{ margin:0; padding:24px; background:#1a1a2e; color:#e0e0e0;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
  h1 {{ color:#e94560; font-size:1.25rem; }}
  a {{ color:#7fdbff; }}
  li {{ margin:8px 0; }}
</style>
</head>
<body>
  <h1>历史摘要归档</h1>
  <p><a href="../">← 返回最新</a></p>
  <ul>
{rows or "    <li>（暂无）</li>"}
  </ul>
</body>
</html>
"""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    (ARCHIVE / "index.html").write_text(listing, encoding="utf-8")

    # Inject history link into latest index if missing
    html = index.read_text(encoding="utf-8")
    if 'href="archive/"' not in html and "href='archive/'" not in html:
        link = '<p class="meta"><a href="archive/" style="color:#7fdbff">历史归档</a></p>\n'
        if '<div class="meta">' in html:
            html = html.replace('<div class="meta">', link + '<div class="meta">', 1)
        else:
            html = html.replace("</h1>", "</h1>\n  " + link, 1)
        index.write_text(html, encoding="utf-8")
        shutil.copy2(index, dest / "index.html")

    print(f"[OK] archived → {dest}")
    print(f"[OK] listing → {ARCHIVE / 'index.html'} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
