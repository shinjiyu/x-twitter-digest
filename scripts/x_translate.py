#!/usr/bin/env python3
"""Translate tweet text for the digest.

X 官方 translations/show.json 已 404（2026-08 实测）。
策略：
  1) 仍尝试 X 接口（若恢复可用）
  2) 回退 Google Translate 匿名 gtx（与网页「翻译」同源引擎之一）
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fetch_tweets import BEARER_TOKEN, SSL_CTX, get_guest_token, load_cookies

TRANSLATE_URLS = (
    "https://x.com/i/api/1.1/translations/show.json",
    "https://api.twitter.com/1.1/translations/show.json",
)

# tweet_id / text hash → (text, source)
_CACHE: dict[str, tuple[str, str]] = {}


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
        "x-twitter-client-language": "zh-cn",
    }
    if cookies:
        h["Cookie"] = cookies["cookie_string"]
        h["x-csrf-token"] = cookies["ct0"]
        h["x-twitter-auth-type"] = "OAuth2Session"
    elif guest_token:
        h["x-guest-token"] = guest_token
    return h


# After first confirmed X 404, skip further X attempts this process.
_X_DEAD = False


def translate_via_x(tweet_id: str, dest: str = "zh") -> str | None:
    global _X_DEAD
    if _X_DEAD or not tweet_id:
        return None
    cookies, _ = load_cookies()
    guest = None
    if not cookies:
        guest = get_guest_token()
        if not guest:
            _X_DEAD = True
            return None

    saw_404 = False
    for dest_try in (dest, "zh-cn"):
        qs = urllib.parse.urlencode({"id": str(tweet_id), "dest": dest_try})
        headers = _headers(cookies=cookies, guest_token=guest)
        for base in TRANSLATE_URLS:
            url = f"{base}?{qs}"
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    saw_404 = True
                if os.environ.get("DEBUG_TRANSLATE"):
                    print(f"  [x-translate] {tweet_id}: HTTP {e.code}", flush=True)
                continue
            except Exception as e:
                if os.environ.get("DEBUG_TRANSLATE"):
                    print(f"  [x-translate] {tweet_id}: {e}", flush=True)
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
    if saw_404:
        _X_DEAD = True
        print("  [x-translate] endpoint 404 — skip X for rest of run, use gtx", flush=True)
    return None


def translate_via_gtx(text: str, dest: str = "zh-CN") -> str | None:
    """Google Translate anonymous endpoint (client=gtx)."""
    text = (text or "").strip()
    if not text:
        return None
    # gtx 对超长文本不友好
    chunk = text[:4500]
    dest_map = {"zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN", "zh-tw": "zh-TW"}
    tl = dest_map.get(dest.lower(), dest) if dest else "zh-CN"
    qs = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "auto",
            "tl": tl,
            "dt": "t",
            "q": chunk,
        }
    )
    url = f"https://translate.googleapis.com/translate_a/single?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # [[ [translated, original, ...], ...], ...]
        parts = []
        for row in data[0] or []:
            if row and row[0]:
                parts.append(row[0])
        out = "".join(parts).strip()
        return out or None
    except Exception as e:
        if os.environ.get("DEBUG_TRANSLATE"):
            print(f"  [gtx] fail: {e}", flush=True)
        return None


def translate_tweet(tweet_id: str, text: str = "", dest: str = "zh") -> tuple[str | None, str]:
    """Return (translated_text, source) where source is x_translate|gtx|None."""
    cache_key = f"{tweet_id}|{dest}|{(text or '')[:80]}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    # 1) X native (often 404 now)
    if os.environ.get("TWITTER_TRANSLATE_X", "1") != "0":
        x = translate_via_x(tweet_id, dest=dest)
        if x:
            _CACHE[cache_key] = (x, "x_translate")
            return x, "x_translate"

    # 2) Google gtx fallback
    if os.environ.get("TWITTER_TRANSLATE_GTX", "1") != "0":
        g = translate_via_gtx(text or "", dest=dest)
        if g:
            _CACHE[cache_key] = (g, "gtx")
            return g, "gtx"

    return None, ""


def looks_mostly_cjk(text: str) -> bool:
    if not text:
        return False
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ch.isalpha() or ("\u4e00" <= ch <= "\u9fff"))
    return letters > 0 and cjk / letters >= 0.4


def truncate_local(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def translate_records(records: list[dict], dest: str = "zh", sleep_s: float = 0.2) -> None:
    """Fill record['summary'] / summary_source; mutate in place."""
    ok_x = 0
    ok_gtx = 0
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
        translated, source = translate_tweet(tid, text=text, dest=dest)
        if translated and source:
            r["summary"] = truncate_local(translated, 200)
            r["summary_source"] = source
            if source == "x_translate":
                ok_x += 1
            else:
                ok_gtx += 1
        else:
            r["summary"] = truncate_local(text, 120)
            r["summary_source"] = "fallback"
            fail += 1
        if sleep_s > 0 and i + 1 < len(records):
            time.sleep(sleep_s)
    print(f"  [translate] x={ok_x} gtx={ok_gtx} skip_zh={skip} fail={fail}")


if __name__ == "__main__":
    import sys

    tid = sys.argv[1] if len(sys.argv) > 1 else ""
    text = sys.argv[2] if len(sys.argv) > 2 else ""
    t, src = translate_tweet(tid, text=text)
    print(src, "→", t or "(none)")
