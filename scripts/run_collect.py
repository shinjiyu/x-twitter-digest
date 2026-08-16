#!/usr/bin/env python3
"""Orchestrate fetch_tweets → gen_table for local / GitHub Actions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
RAW = ROOT / "raw"
SITE = ROOT / "site"
ACCOUNTS = ROOT / "accounts.json"


def main() -> int:
    cfg = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    hours = int(os.environ.get("TWITTER_HOURS_WINDOW", cfg.get("hours_window", 8)))
    count = int(os.environ.get("TWITTER_COUNT", cfg.get("count_per_account", 20)))
    accounts = [a["screen_name"] for a in cfg.get("accounts", [])]
    if not accounts:
        print("[ERROR] accounts.json has no accounts", file=sys.stderr)
        return 1

    RAW.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["TWEET_DIR"] = str(RAW)
    env["OUTPUT_DIR"] = str(SITE)
    env["TWITTER_HOURS_WINDOW"] = str(hours)

    ok = 0
    fail = 0
    for i, name in enumerate(accounts):
        out = RAW / f"tweets_{name}.json"
        env["OUTPUT_FILE"] = str(out)
        print(f"\n[{i + 1}/{len(accounts)}] @{name}")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "fetch_tweets.py"), name, str(count)],
            cwd=str(ROOT),
            env=env,
        )
        if r.returncode == 0:
            ok += 1
        else:
            fail += 1
            print(f"  [WARN] fetch failed exit={r.returncode}", file=sys.stderr)
        if i + 1 < len(accounts):
            time.sleep(float(os.environ.get("TWITTER_FETCH_SLEEP", "1.5")))

    print(f"\n=== fetch done: ok={ok} fail={fail} ===")
    r2 = subprocess.run(
        [sys.executable, str(SCRIPTS / "gen_table.py")],
        cwd=str(ROOT),
        env=env,
    )
    if r2.returncode != 0:
        return r2.returncode

    index = SITE / "index.html"
    if not index.is_file() or index.stat().st_size <= 0:
        print("[ERROR] site/index.html missing", file=sys.stderr)
        return 1

    print(f"[DONE] page → {index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
