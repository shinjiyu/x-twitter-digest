#!/usr/bin/env python3
"""Scan tweets_*.json → tweets_summary.json + polished HTML (config-driven)."""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config_loader import account_camp_lookup, camp_meta, camp_order_map, load_config

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


def truncate(text: str, max_len: int = 200) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def parse_created_at_dt(created_at_str: str):
    try:
        return datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None


def parse_created_at(created_at_str: str) -> str:
    dt = parse_created_at_dt(created_at_str)
    if dt is None:
        return created_at_str or ""
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def hours_window(default: int = 168) -> int:
    raw = os.environ.get("TWITTER_HOURS_WINDOW", str(default)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def filter_by_hours_window(records, hours):
    if hours <= 0:
        return records, 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept, dropped = [], 0
    for r in records:
        dt = parse_created_at_dt(r.get("created_at", ""))
        if dt is None:
            dropped += 1
            continue
        if dt.astimezone(timezone.utc) >= cutoff:
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped


def load_tweets(tweet_dir: str, cfg: dict):
    lookup = account_camp_lookup(cfg)
    pattern = os.path.join(tweet_dir, "tweets_*.json")
    all_records = []

    for filepath in sorted(glob.glob(pattern)):
        if "_raw" in os.path.basename(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [WARN] Failed to load {filepath}: {e}")
            continue

        screen_name = data.get("screen_name", "")
        if not screen_name:
            continue

        camp_info = lookup.get(screen_name) or lookup.get(screen_name.lower())
        if not camp_info:
            z = camp_meta(cfg, "Z")
            camp_info = ("Z", z.get("name", "其他"), z.get("emoji", "·"), z.get("color", "#6b7280"))
            print(f"  [WARN] @{screen_name} not in accounts.json → camp Z")

        camp_id, camp_name, camp_emoji, camp_color = camp_info
        display_name = data.get("user_name", screen_name)

        for tweet in data.get("tweets", []):
            full_text = tweet.get("full_text", "")
            all_records.append(
                {
                    "camp": camp_id,
                    "camp_name": camp_name,
                    "camp_emoji": camp_emoji,
                    "camp_color": camp_color,
                    "screen_name": screen_name,
                    "display_name": display_name,
                    "id_str": tweet.get("id_str", ""),
                    "created_at": tweet.get("created_at", ""),
                    "created_at_fmt": parse_created_at(tweet.get("created_at", "")),
                    "full_text": full_text,
                    "full_text_en_200": truncate(full_text, 280),
                    "lang": tweet.get("lang", ""),
                    "summary": "",
                    "summary_source": "",
                    "retweet_count": tweet.get("retweet_count", 0),
                    "favorite_count": tweet.get("favorite_count", 0),
                    "reply_count": tweet.get("reply_count", 0),
                    "quote_count": tweet.get("quote_count", 0),
                }
            )
    return all_records


def generate_analysis(records) -> str:
    if not records:
        return "本轮时间窗内无推文。"
    by_user = {}
    for r in records:
        sn = r.get("screen_name") or "?"
        by_user.setdefault(sn, {"n": 0, "fav": 0})
        by_user[sn]["n"] += 1
        by_user[sn]["fav"] += int(r.get("favorite_count") or 0)
    top = sorted(by_user.items(), key=lambda x: (x[1]["fav"], x[1]["n"]), reverse=True)[:5]
    bits = [f"@{u} {v['n']}条 · 赞{v['fav']}" for u, v in top]
    src = sum(1 for r in records if r.get("summary_source") == "x_translate")
    return f"共 {len(records)} 条，X 翻译 {src} 条。互动靠前：{' · '.join(bits) if bits else '无'}。"


def load_timeline_manifest(site_dir: str | Path) -> list[dict]:
    path = Path(site_dir) / "archive" / "manifest.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("entries") or [])
    except (json.JSONDecodeError, OSError):
        return []


def generate_html(
    records,
    *,
    cfg: dict,
    hours: int = 0,
    page_kind: str = "latest",
    current_stamp: str | None = None,
    timeline: list[dict] | None = None,
) -> str:
    """page_kind: latest | archive. Timeline entries from manifest."""
    order = camp_order_map(cfg)
    title = cfg.get("title") or "X 摘要"
    subtitle = cfg.get("subtitle") or ""
    timeline = timeline if timeline is not None else []

    camps: dict[str, list] = {}
    for r in records:
        camps.setdefault(r["camp"], []).append(r)

    sections = []
    for camp_id in sorted(camps.keys(), key=lambda c: order.get(c, 99)):
        camp_records = camps[camp_id]
        meta = camp_meta(cfg, camp_id)
        color = meta.get("color") or "#6b7280"
        name = meta.get("name") or camp_id
        emoji = meta.get("emoji") or ""
        cards = []
        for r in camp_records:
            sn = esc(r.get("screen_name", ""))
            tid = esc(r.get("id_str", ""))
            href = f"https://x.com/{sn}/status/{tid}" if tid else f"https://x.com/{sn}"
            src_badge = {
                "x_translate": "X 翻译",
                "original": "原文",
                "fallback": "未译",
            }.get(r.get("summary_source") or "", "")
            cards.append(
                f"""
<article class="card">
  <header class="card-hd">
    <a class="who" href="https://x.com/{sn}" target="_blank" rel="noopener">@{sn}</a>
    <time>{esc(r.get('created_at_fmt', ''))}</time>
  </header>
  <p class="zh">{esc(r.get('summary') or '')}</p>
  <p class="en">{esc(r.get('full_text_en_200') or '')}</p>
  <footer class="card-ft">
    <span>转发 {int(r.get('retweet_count') or 0)}</span>
    <span>点赞 {int(r.get('favorite_count') or 0)}</span>
    <span>回复 {int(r.get('reply_count') or 0)}</span>
    {f'<span class="badge">{esc(src_badge)}</span>' if src_badge else ''}
    <a class="src" href="{href}" target="_blank" rel="noopener">原文</a>
  </footer>
</article>"""
            )
        sections.append(
            f"""
<section class="camp" style="--camp:{esc(color)}">
  <div class="camp-hd">
    <h2><span class="mark">{esc(emoji)}</span> {esc(name)}</h2>
    <span class="count">{len(camp_records)} 条</span>
  </div>
  <div class="cards">{''.join(cards)}</div>
</section>"""
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = "".join(sections) if sections else (
        f'<p class="empty">过去 {hours} 小时内无新推文。</p>' if hours > 0 else '<p class="empty">暂无推文。</p>'
    )
    analysis = esc(generate_analysis(records))

    # relative paths for timeline
    if page_kind == "archive":
        latest_href = "../../"
        manifest_href = "../manifest.json"
        archive_prefix = "../"
    else:
        latest_href = "./"
        manifest_href = "archive/manifest.json"
        archive_prefix = "archive/"

    stamp_label = current_stamp or "最新"
    meta_bits = [f"生成 {now}", f"{len(records)} 条"]
    if hours > 0:
        meta_bits.insert(1, f"窗 {hours}h")

    # server-rendered timeline chips (JS refreshes from manifest if available)
    chips = [
        f'<a class="chip {"is-on" if page_kind == "latest" else ""}" href="{latest_href}" data-stamp="latest">最新</a>'
    ]
    for e in timeline[:40]:
        st = e.get("stamp") or ""
        if not st:
            continue
        kept = e.get("kept_count")
        label = st.replace("T", " ").replace("Z", "")
        on = "is-on" if st == current_stamp else ""
        chips.append(
            f'<a class="chip {on}" href="{archive_prefix}{esc(st)}/" data-stamp="{esc(st)}">'
            f"{esc(label)}"
            f'{f" · {kept}" if kept is not None else ""}</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(title)} · {esc(stamp_label)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet"/>
<style>
:root {{
  --bg: #0e1116;
  --bg2: #161b22;
  --ink: #e8edf2;
  --muted: #8b949e;
  --line: #30363d;
  --accent: #3dd6c6;
  --card: #12171e;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(1200px 500px at 10% -10%, #1a2a28 0%, transparent 55%),
    radial-gradient(900px 400px at 100% 0%, #1c2230 0%, transparent 50%),
    var(--bg);
  font-family: "Noto Sans SC", system-ui, sans-serif;
  line-height: 1.55;
}}
.wrap {{ max-width: 920px; margin: 0 auto; padding: 20px 16px 64px; }}
.hero {{
  padding: 8px 0 18px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 14px;
}}
.hero h1 {{
  margin: 0;
  font-family: Fraunces, "Noto Serif SC", serif;
  font-weight: 700;
  font-size: clamp(1.55rem, 4vw, 2.1rem);
  letter-spacing: 0.02em;
}}
.hero .sub {{ color: var(--muted); margin: 8px 0 0; font-size: 0.95rem; }}
.hero .meta {{ color: var(--muted); margin-top: 10px; font-size: 0.82rem; }}
.timeline-bar {{
  position: sticky; top: 0; z-index: 20;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line);
  margin: 0 -16px 18px;
  padding: 10px 16px 12px;
}}
.timeline-bar .label {{
  font-size: 0.75rem; color: var(--muted); letter-spacing: 0.08em;
  text-transform: uppercase; margin-bottom: 8px;
}}
.rail {{
  display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px;
  -webkit-overflow-scrolling: touch; scrollbar-width: thin;
}}
.chip {{
  flex: 0 0 auto;
  text-decoration: none;
  color: var(--ink);
  border: 1px solid var(--line);
  background: var(--bg2);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.78rem;
  white-space: nowrap;
}}
.chip.is-on, .chip:hover {{
  border-color: var(--accent);
  color: var(--accent);
}}
.summary-box {{
  background: var(--bg2);
  border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
  color: #c9d1d9;
}}
.camp {{ margin-bottom: 22px; }}
.camp-hd {{
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 12px; margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid color-mix(in srgb, var(--camp) 55%, var(--line));
}}
.camp-hd h2 {{
  margin: 0; font-size: 1.05rem; font-weight: 700;
  display: flex; align-items: center; gap: 8px;
}}
.camp-hd .mark {{ color: var(--camp); }}
.camp-hd .count {{ color: var(--muted); font-size: 0.8rem; }}
.cards {{ display: grid; gap: 10px; }}
.card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 14px 12px;
  border-top: 2px solid color-mix(in srgb, var(--camp) 70%, transparent);
}}
.card-hd {{
  display: flex; justify-content: space-between; gap: 10px;
  margin-bottom: 8px; font-size: 0.82rem;
}}
.card-hd .who {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
.card-hd time {{ color: var(--muted); }}
.card .zh {{
  margin: 0 0 8px;
  font-size: 1.02rem;
  font-weight: 500;
  line-height: 1.6;
}}
.card .en {{
  margin: 0;
  color: var(--muted);
  font-size: 0.86rem;
  line-height: 1.5;
}}
.card-ft {{
  display: flex; flex-wrap: wrap; gap: 10px 14px;
  margin-top: 12px; padding-top: 10px;
  border-top: 1px dashed var(--line);
  color: var(--muted); font-size: 0.75rem;
}}
.card-ft .badge {{
  border: 1px solid var(--line); border-radius: 6px; padding: 1px 6px;
}}
.card-ft .src {{ margin-left: auto; color: var(--accent); text-decoration: none; }}
.empty {{ text-align: center; color: var(--muted); padding: 40px 12px; }}
@media (max-width: 640px) {{
  .wrap {{ padding: 14px 12px 48px; }}
  .card-ft .src {{ margin-left: 0; }}
}}
</style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>{esc(title)}</h1>
      <p class="sub">{esc(subtitle)}</p>
      <p class="meta">{esc(" · ".join(meta_bits))} · 视图 {esc(stamp_label)}</p>
    </header>

    <nav class="timeline-bar" aria-label="时间轴">
      <div class="label">时间轴 · 切换历史快照</div>
      <div class="rail" id="timeline-rail">{''.join(chips)}</div>
    </nav>

    <div class="summary-box">{analysis}</div>
    {body}
  </div>
  <script>
  (function () {{
    var manifestHref = {json.dumps(manifest_href)};
    var archivePrefix = {json.dumps(archive_prefix)};
    var latestHref = {json.dumps(latest_href)};
    var current = {json.dumps(current_stamp or "latest")};
    var rail = document.getElementById("timeline-rail");
    if (!rail) return;
    fetch(manifestHref, {{ cache: "no-store" }}).then(function (r) {{
      if (!r.ok) throw new Error("no manifest");
      return r.json();
    }}).then(function (data) {{
      var entries = (data && data.entries) || [];
      var html = '<a class="chip' + (current === "latest" ? " is-on" : "") +
        '" href="' + latestHref + '" data-stamp="latest">最新</a>';
      entries.slice(0, 48).forEach(function (e) {{
        var st = e.stamp || "";
        if (!st) return;
        var on = st === current ? " is-on" : "";
        var label = st.replace("T", " ").replace("Z", "");
        var kept = (e.kept_count != null) ? (" · " + e.kept_count) : "";
        html += '<a class="chip' + on + '" href="' + archivePrefix + st +
          '/" data-stamp="' + st + '">' + label + kept + "</a>";
      }});
      rail.innerHTML = html;
    }}).catch(function () {{ /* keep server chips */ }});
  }})();
  </script>
</body>
</html>"""


def write_outputs(
    records,
    *,
    cfg: dict,
    hours: int,
    raw_count: int,
    dropped: int,
    workspace_dir: str,
    timeline: list[dict] | None = None,
    page_kind: str = "latest",
    current_stamp: str | None = None,
) -> str:
    os.makedirs(workspace_dir, exist_ok=True)
    json_path = os.path.join(workspace_dir, "tweets_summary.json")
    json_records = []
    for r in records:
        json_records.append(
            {
                "camp": r["camp"],
                "camp_name": r["camp_name"],
                "screen_name": r["screen_name"],
                "display_name": r["display_name"],
                "created_at": r["created_at"],
                "id_str": r["id_str"],
                "full_text": r["full_text"],
                "full_text_en_200": r["full_text_en_200"],
                "summary": r["summary"],
                "summary_source": r.get("summary_source", ""),
                "retweet_count": r["retweet_count"],
                "favorite_count": r["favorite_count"],
                "reply_count": r["reply_count"],
                "hours_window": hours,
            }
        )
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours_window": hours,
        "raw_count": raw_count,
        "kept_count": len(records),
        "dropped_count": dropped,
        "title": cfg.get("title"),
        "tweets": json_records,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if timeline is None:
        timeline = load_timeline_manifest(workspace_dir if page_kind == "latest" else Path(workspace_dir).parents[1])

    html = generate_html(
        records,
        cfg=cfg,
        hours=hours,
        page_kind=page_kind,
        current_stamp=current_stamp,
        timeline=timeline,
    )
    for name in ("index.html", "tweets_summary.html"):
        with open(os.path.join(workspace_dir, name), "w", encoding="utf-8") as f:
            f.write(html)
    return json_path


def records_from_summary(path: str | Path, cfg: dict) -> tuple[list, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lookup = account_camp_lookup(cfg)
    records = []
    for t in data.get("tweets") or []:
        sn = t.get("screen_name") or ""
        camp_info = lookup.get(sn) or lookup.get(sn.lower())
        if not camp_info:
            z = camp_meta(cfg, "Z")
            camp_info = ("Z", z.get("name", "其他"), z.get("emoji", "·"), z.get("color", "#6b7280"))
        camp_id, camp_name, camp_emoji, camp_color = camp_info
        records.append(
            {
                **t,
                "camp": camp_id,
                "camp_name": camp_name,
                "camp_emoji": camp_emoji,
                "camp_color": camp_color,
                "created_at_fmt": parse_created_at(t.get("created_at", "")),
                "full_text_en_200": t.get("full_text_en_200") or truncate(t.get("full_text") or "", 280),
            }
        )
    return records, data


def main() -> int:
    cfg = load_config()
    tweet_dir = os.environ.get("TWEET_DIR") or str(ROOT / "raw")
    workspace_dir = os.environ.get("OUTPUT_DIR") or str(ROOT / "site")
    hours = hours_window(int(cfg.get("hours_window", 168)))

    print("=== gen_table.py ===")
    print(f"  推文目录: {tweet_dir}")
    print(f"  输出目录: {workspace_dir}")
    print(f"  配置: accounts.json · {len(cfg.get('accounts') or [])} 账号")

    os.makedirs(workspace_dir, exist_ok=True)
    print("[STEP 1] 扫描 tweets_*.json ...")
    raw_records = load_tweets(tweet_dir, cfg)
    records, dropped = filter_by_hours_window(raw_records, hours)
    print(f"  [OK] 原始 {len(raw_records)} → 窗 {hours}h 保留 {len(records)}（丢 {dropped}）")
    if not raw_records:
        print("[WARN] 未找到推文，仍写空页")

    print("[STEP 1b] X 原生翻译 ...")
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from x_translate import translate_records

    sleep_s = float(os.environ.get("TWITTER_TRANSLATE_SLEEP", "0.35"))
    translate_records(records, dest=os.environ.get("TWITTER_TRANSLATE_DEST", "zh"), sleep_s=sleep_s)

    print("[STEP 2/3] 写 JSON + HTML ...")
    write_outputs(
        records,
        cfg=cfg,
        hours=hours,
        raw_count=len(raw_records),
        dropped=dropped,
        workspace_dir=workspace_dir,
        page_kind="latest",
    )
    print("tweets_summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
