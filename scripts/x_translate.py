#!/usr/bin/env python3
"""Call X native tweet translation (same as in-app Translate)."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from fetch_tweets import BEARER_TOKEN, SSL_CTX, get_guest_token, load_cookies

TRANSLATE_URLS = (
    "https://x.com/i/api/1.1/translations/show.json",
    "https://api.twitter.com/1.1/translations/show.json",
)


def _headers(cookies=None, guest_token=None):
    h = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": "https://x.com/",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "zh",
    }
    if cookies:
        h["Cookie"] = cookies["cookie_string"]
        h["x-csrf-token"] = cookies["ct0"]
        h["x-twitter-auth-type"] = "OAuth2Session"
    elif guest_token:
        h["x-guest-token"] = guest_token
    return h


def translate_tweet(tweet_id: str, dest: str = "zh") -> str | None:
    """Return X translation text, or None on failure."""
    if not tweet_id:
        return None
    cookies, _ = load_cookies()
    guest = None
    if not cookies:
        guest = get_guest_token()
        if not guest:
            return None

    qs = urllib.parse.urlencode({"id": str(tweet_id), "dest": dest})
    headers = _headers(cookies=cookies, guest_token=guest)
    last_err = None
    for base in TRANSLATE_URLS:
        url = f"{base}?{qs}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            continue
        text = (
            data.get("translation")
            or data.get("text")
            or data.get("translated_text")
            or ""
        )
        if isinstance(text, dict):
            text = text.get("text") or ""
        text = (text or "").strip()
        if text:
            return text
    if last_err and os.environ.get("DEBUG_TRANSLATE"):
        print(f"  [translate] fail {tweet_id}: {last_err}", flush=True)
    return None


def looks_mostly_cjk(text: str) -> bool:
    if not text:
        return False
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ch.isalpha() or ("\u4e00" <= ch <= "\u9fff"))
    return letters > 0 and cjk / letters >= 0.4


def translate_records(records: list[dict], dest: str = "zh", sleep_s: float = 0.35) -> None:
    """Fill record['summary'] via X translate; mutate in place."""
    ok = 0
    skip = 0
    fail = 0
    for i, r in enumerate(records):
        text = r.get("full_text") or ""
        lang = (r.get("lang") or "").lower()
        if lang.startswith("zh") or looks_mostly_cjk(text):
            r["summary"] = truncate_local(text, 120)
            r["summary_source"] = "original"
            skip += 1
            continue
        tid = r.get("id_str") or ""
        translated = translate_tweet(tid, dest=dest)
        if translated:
            r["summary"] = truncate_local(translated, 200)
            r["summary_source"] = "x_translate"
            ok += 1
        else:
            r["summary"] = truncate_local(text, 80) + "（X翻译不可用）"
            r["summary_source"] = "fallback"
            fail += 1
        if sleep_s > 0 and i + 1 < len(records):
            time.sleep(sleep_s)
    print(f"  [translate] ok={ok} skip_zh={skip} fail={fail}")


def truncate_local(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


if __name__ == "__main__":
    import sys

    tid = sys.argv[1] if len(sys.argv) > 1 else ""
    print(translate_tweet(tid) or "(none)")
