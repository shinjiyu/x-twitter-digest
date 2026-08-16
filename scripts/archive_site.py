#!/usr/bin/env python3
"""Snapshot site/ → site/archive/<stamp>/ + manifest + timeline-aware HTML."""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from config_loader import load_config
from gen_table import records_from_summary, write_outputs

ROOT = SCRIPT_DIR.parent
SITE = ROOT / "site"
ARCHIVE = SITE / "archive"


def collect_entries() -> list[dict]:
    entries = []
    if not ARCHIVE.is_dir():
        return entries
    for p in sorted(ARCHIVE.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{4}Z", p.name):
            continue
        meta = {
            "stamp": p.name,
            "kept_count": None,
            "hours_window": None,
            "archived_at": None,
        }
        mpath = p / "meta.json"
        if mpath.is_file():
            try:
                m = json.loads(mpath.read_text(encoding="utf-8"))
                meta.update(
                    {
                        "kept_count": m.get("kept_count"),
                        "hours_window": m.get("hours_window"),
                        "archived_at": m.get("archived_at") or m.get("generated_at"),
                    }
                )
            except json.JSONDecodeError:
                pass
        entries.append(meta)
    return entries


def write_manifest(entries: list[dict]) -> Path:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE / "manifest.json"
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # lightweight listing page
    lines = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'/>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>",
        "<title>归档索引</title></head><body style='font-family:sans-serif;padding:24px'>",
        "<h1>归档</h1><p><a href='../'>最新</a></p><ul>",
    ]
    for e in entries:
        st = e["stamp"]
        lines.append(
            f"<li><a href='{st}/'>{st}</a> · 推文 {e.get('kept_count')} · 窗 {e.get('hours_window')}h</li>"
        )
    lines.append("</ul></body></html>")
    (ARCHIVE / "index.html").write_text("\n".join(lines), encoding="utf-8")
    return path


def refresh_html(cfg: dict, entries: list[dict], stamp: str) -> None:
    """Rebuild latest + this stamp pages so timeline is consistent."""
    summary = SITE / "tweets_summary.json"
    if not summary.is_file():
        return
    records, data = records_from_summary(summary, cfg)
    hours = int(data.get("hours_window") or 0)
    raw_count = int(data.get("raw_count") or len(records))
    dropped = int(data.get("dropped_count") or 0)

    write_outputs(
        records,
        cfg=cfg,
        hours=hours,
        raw_count=raw_count,
        dropped=dropped,
        workspace_dir=str(SITE),
        timeline=entries,
        page_kind="latest",
        current_stamp=None,
    )

    dest = ARCHIVE / stamp
    # archive page uses same tweet set as this snapshot
    dest_summary = dest / "tweets_summary.json"
    if dest_summary.is_file():
        arec, adata = records_from_summary(dest_summary, cfg)
        write_outputs(
            arec,
            cfg=cfg,
            hours=int(adata.get("hours_window") or hours),
            raw_count=int(adata.get("raw_count") or len(arec)),
            dropped=int(adata.get("dropped_count") or 0),
            workspace_dir=str(dest),
            timeline=entries,
            page_kind="archive",
            current_stamp=stamp,
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

    entries = collect_entries()
    write_manifest(entries)
    cfg = load_config()
    refresh_html(cfg, entries, stamp)

    print(f"[OK] archived → {dest}")
    print(f"[OK] manifest entries={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
