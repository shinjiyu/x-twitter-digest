#!/usr/bin/env python3
"""
gen_table.py — 扫描 .run/ew/tweets_*.json，按阵营分组生成表格化 deliverable。
纯 stdlib 实现，无第三方依赖。

输出:
  workspace/tweets_summary.html — HTML 表格（深色主题、手机友好）
  workspace/tweets_summary.json — 结构化数据
"""

import json
import sys
import os
import glob
import re
from datetime import datetime, timezone, timedelta

# ── 阵营映射 ──────────────────────────────────────────────
CAMP_MAP = {
    # A: 台湾科技产业
    "HTC":             ("A", "台湾科技产业", "🔧"),
    "ASUS":            ("A", "台湾科技产业", "🔧"),
    "msigaming":       ("A", "台湾科技产业", "🔧"),
    "MediaTek":        ("A", "台湾科技产业", "🔧"),
    "acer":            ("A", "台湾科技产业", "🔧"),
    "dylan522p":       ("A", "台湾科技产业", "🔧"),
    "trendforce":      ("A", "台湾科技产业", "🔧"),
    "DIGITIMES":       ("A", "台湾科技产业", "🔧"),
    # B: 台湾政治军事
    "IanEaston1":      ("B", "台湾政治军事", "🏛️"),
    "BonnyLin4":       ("B", "台湾政治军事", "🏛️"),
    "brianhioe":       ("B", "台湾政治军事", "🏛️"),
    "GlobalTaiwan":    ("B", "台湾政治军事", "🏛️"),
    "RandalSchriver":  ("B", "台湾政治军事", "🏛️"),
    "changlept":       ("B", "台湾政治军事", "🏛️"),
    "KharisTempleman": ("B", "台湾政治军事", "🏛️"),
    # C: 两岸地缘政治
    "shashj":          ("C", "两岸地缘政治", "🌍"),
    "BonnieGlaser":    ("C", "两岸地缘政治", "🌍"),
    "joshuakucera":    ("C", "两岸地缘政治", "🌍"),
    "Wang_Maya":       ("C", "两岸地缘政治", "🌍"),
}

CAMP_ORDER = {"A": 0, "B": 1, "C": 2, "Z": 9}

# ── 中文摘要关键词匹配规则 ─────────────────────────────────
SUMMARY_RULES = [
    # 半导体/芯片
    (["chip", "semiconductor", "wafer", "foundry", "TSMC", "ASML", "AMD", "Nvidia", "NVDA", "GPU", "HBM"],
     "半导体/芯片产业链"),
    (["capex", "capital expenditure", "spending", "data center", "hyperscaler"],
     "资本开支/数据中心"),
    (["earnings", "revenue", "guidance", "quarter", "Q1", "Q2", "Q3", "Q4", "beat", "miss"],
     "财报/业绩"),
    (["bubble", "overvalued", "short", "bearish", "crash", "froth", "specul"],
     "看空/泡沫警告"),
    (["AI", "artificial intelligence", "LLM", "GPT", "model", "training", "inference"],
     "AI技术/模型"),
    (["rate", "Fed", "interest", "yield", "treasury", "inflation", "CPI"],
     "宏观/利率/通胀"),
    (["supply chain", "shortage", "inventory", "demand", "capacity"],
     "供需/库存"),
    (["valuation", "PE", "P/E", "multiple", "DCF", "discount"],
     "估值分析"),
    (["options", "put", "call", "hedge", "volatility", "VIX"],
     "期权/波动率"),
    (["risk", "credit", "leverage", "debt", "default"],
     "风险/信用"),
]

# 中文关键词
SUMMARY_RULES_CN = [
    (["半导体", "芯片", "晶圆", "代工", "光刻"], "半导体/芯片产业链"),
    (["资本开支", "capex", "数据中心", "算力"], "资本开支/数据中心"),
    (["财报", "营收", "业绩", "指引", "盈利"], "财报/业绩"),
    (["泡沫", "高估", "做空", "熊市", "崩盘"], "看空/泡沫警告"),
    (["估值", "PE", "市盈率", "折现"], "估值分析"),
    (["利率", "通胀", "美联储", "降息", "加息"], "宏观/利率/通胀"),
    (["供应链", "短缺", "库存", "需求", "产能"], "供需/库存"),
    (["期权", "对冲", "波动率", "风险"], "期权/波动率"),
    (["AI", "人工智能", "模型", "训练", "推理"], "AI技术/模型"),
    (["风险", "信用", "杠杆", "债务", "违约"], "风险/信用"),
]


def generate_summary(text):
    """调用智谱GLM API将英文推文翻译为简洁中文摘要（50字以内）。"""
    import os
    import json
    import urllib.request

    api_key = os.environ.get('ZHIPU_API_KEY', '')
    if not api_key or not text or not text.strip():
        return text[:50] + "(翻译失败)" if text else ""

    prompt = (
        "请将以下英文推文翻译成简洁的中文摘要，要求50字以内，"
        "只输出中文翻译结果，不要加任何解释或多余内容：\n\n" + text[:500]
    )

    payload = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 120,
    }

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        summary = result["choices"][0]["message"]["content"].strip()
        if not summary:
            return text[:50] + "(翻译失败)"
        return summary
    except Exception:
        return text[:50] + "(翻译失败)"


def truncate(text, max_len=200):
    """截断文本到指定长度。"""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def parse_created_at_dt(created_at_str):
    """Parse Twitter created_at → aware datetime, or None."""
    try:
        return datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None


def parse_created_at(created_at_str):
    """将 Twitter 时间格式 'Wed Jul 22 20:24:01 +0000 2026' 转为可读格式。"""
    dt = parse_created_at_dt(created_at_str)
    if dt is None:
        return created_at_str
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def hours_window():
    """日历对齐：默认只保留过去 N 小时内的推文（TWITTER_HOURS_WINDOW，默认 8）。0=不过滤。"""
    raw = os.environ.get("TWITTER_HOURS_WINDOW", "8").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 8


def filter_by_hours_window(records, hours):
    if hours <= 0:
        return records, 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept = []
    dropped = 0
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


def load_tweets(tweet_dir):
    """扫描目录中的 tweets_*.json 文件（排除 _raw 文件）。"""
    pattern = os.path.join(tweet_dir, "tweets_*.json")
    all_records = []

    for filepath in sorted(glob.glob(pattern)):
        basename = os.path.basename(filepath)
        if "_raw" in basename:
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  [WARN] Failed to load {filepath}: {e}")
            continue

        screen_name = data.get("screen_name", "")
        if not screen_name:
            continue

        camp_info = CAMP_MAP.get(screen_name) or CAMP_MAP.get(screen_name.lower())
        if not camp_info:
            camp_info = ("Z", "其他", "📎")
            print(f"  [WARN] Unknown screen_name: {screen_name}, using camp Z")

        camp_id, camp_name, camp_emoji = camp_info
        display_name = data.get("user_name", screen_name)

        for tweet in data.get("tweets", []):
            full_text = tweet.get("full_text", "")
            record = {
                "camp": camp_id,
                "camp_name": camp_name,
                "camp_emoji": camp_emoji,
                "screen_name": screen_name,
                "display_name": display_name,
                "id_str": tweet.get("id_str", ""),
                "created_at": tweet.get("created_at", ""),
                "created_at_fmt": parse_created_at(tweet.get("created_at", "")),
                "full_text": full_text,
                "full_text_en_200": truncate(full_text, 200),
                "summary": generate_summary(full_text),
                "retweet_count": tweet.get("retweet_count", 0),
                "favorite_count": tweet.get("favorite_count", 0),
                "reply_count": tweet.get("reply_count", 0),
                "quote_count": tweet.get("quote_count", 0),
            }
            all_records.append(record)

    return all_records



def generate_analysis(records):
    """调用 GLM-4-flash 生成 100-200 字中文趋势分析。"""
    import os, json, urllib.request
    try:
        tweets_text = "\n".join(
            f"@{r.get('screen_name','')}: {(r.get('full_text_en_200') or '')[:100]}"
            for r in records[:50]
        )
        prompt = f"请用100-200字中文总结以下推文的整体趋势和重点：\n{tweets_text}"
        api_key = os.environ.get("ZHIPU_API_KEY", "")
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        payload = json.dumps({
            "model": "glm-4-flash",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except Exception:
        return "本轮暂无分析。"


def generate_html(records, hours=0):
    """生成深色主题、手机友好的 HTML 表格报告。"""
    camp_names = {
        "A": "台湾科技产业",
        "B": "台湾政治军事",
        "C": "两岸地缘政治",
        "Z": "其他",
    }
    camp_emojis = {"A": "🔧", "B": "🏛️", "C": "🌍", "Z": "📎"}

    camps = {}
    for r in records:
        key = r["camp"]
        camps.setdefault(key, []).append(r)

    sections = []
    for camp_id in sorted(camps.keys(), key=lambda c: CAMP_ORDER.get(c, 99)):
        camp_records = camps[camp_id]
        emoji = camp_emojis.get(camp_id, "")
        name = camp_names.get(camp_id, camp_id)
        rows = []
        for r in camp_records:
            text = (r.get("full_text_en_200") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            summary = (r.get("summary") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows.append(
                "<tr>"
                f"<td>{r.get('created_at_fmt', '')}</td>"
                f"<td>@{r.get('screen_name', '')}</td>"
                f"<td>{text}</td>"
                f"<td>{summary}</td>"
                f"<td class=\"num\">{r.get('retweet_count', 0)}</td>"
                f"<td class=\"num\">{r.get('favorite_count', 0)}</td>"
                f"<td class=\"num\">{r.get('reply_count', 0)}</td>"
                "</tr>"
            )
        total_rt = sum(r["retweet_count"] for r in camp_records)
        total_fav = sum(r["favorite_count"] for r in camp_records)
        total_reply = sum(r["reply_count"] for r in camp_records)
        sections.append(
            f"<section class=\"camp\"><h2>{emoji} {name}</h2>"
            "<div class=\"table-wrap\"><table>"
            "<thead><tr><th>发博时间</th><th>博主</th><th>英文原文</th><th>中文核心观点</th>"
            "<th>转发</th><th>点赞</th><th>回复</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            f"<tfoot><tr class=\"sum\"><td colspan=\"4\">阵营互动汇总（{len(camp_records)} 条）</td>"
            f"<td class=\"num\">{total_rt}</td><td class=\"num\">{total_fav}</td>"
            f"<td class=\"num\">{total_reply}</td></tr></tfoot>"
            "</table></div></section>"
        )

    overall_rows = []
    for camp_id in sorted(camps.keys(), key=lambda c: CAMP_ORDER.get(c, 99)):
        cr = camps[camp_id]
        emoji = camp_emojis.get(camp_id, "")
        name = camp_names.get(camp_id, camp_id)
        overall_rows.append(
            "<tr>"
            f"<td>{emoji} {camp_id}-{name}</td>"
            f"<td class=\"num\">{len(cr)}</td>"
            f"<td class=\"num\">{sum(r['retweet_count'] for r in cr)}</td>"
            f"<td class=\"num\">{sum(r['favorite_count'] for r in cr)}</td>"
            f"<td class=\"num\">{sum(r['reply_count'] for r in cr)}</td>"
            "</tr>"
        )
    overall_rows.append(
        "<tr class=\"sum\"><td>合计</td>"
        f"<td class=\"num\">{len(records)}</td>"
        f"<td class=\"num\">{sum(r['retweet_count'] for r in records)}</td>"
        f"<td class=\"num\">{sum(r['favorite_count'] for r in records)}</td>"
        f"<td class=\"num\">{sum(r['reply_count'] for r in records)}</td></tr>"
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = "".join(sections) if sections else f"<p class=\"empty\">过去 {hours} 小时内无新推文。</p>"
    meta_bits = [f"生成时间: {now}", f"总推文数: {len(records)}"]
    if hours > 0:
        meta_bits.insert(1, f"时间窗: 过去 {hours} 小时")
    meta_html = " · ".join(meta_bits)

    analysis_text = generate_analysis(records)
    analysis_html = f'<section class="camp"><h2>📊 个人分析</h2><p style="line-height:1.8;color:#ccc;">{analysis_text}</p></section>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>台湾主题推文追踪报告</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 12px; background: #1a1a2e; color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    line-height: 1.5; }}
  h1 {{ color: #e94560; font-size: 1.35rem; text-align: center; margin: 0 0 8px; }}
  .meta {{ text-align: center; color: #888; font-size: 0.85rem; margin-bottom: 16px; }}
  .camp {{ background: #16213e; border-radius: 10px; padding: 12px; margin-bottom: 14px; }}
  .camp h2 {{ color: #e94560; font-size: 1.05rem; margin: 0 0 10px; }}
  .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; min-width: 560px; }}
  th {{ background: #0f3460; color: #e0e0e0; text-align: left; padding: 8px 6px; white-space: nowrap; }}
  td {{ padding: 7px 6px; border-bottom: 1px solid #1a1a2e; vertical-align: top; word-break: break-word; }}
  td.num, th.num {{ text-align: center; white-space: nowrap; }}
  tr.sum td {{ background: #0f3460; font-weight: 600; color: #e94560; }}
  .empty {{ text-align: center; color: #aaa; padding: 24px; }}
  @media (max-width: 600px) {{
    body {{ padding: 8px; }}
    h1 {{ font-size: 1.15rem; }}
    table {{ font-size: 0.72rem; }}
  }}
</style>
</head>
<body>
  <h1>📊 台湾主题推文追踪报告</h1>
  <div class="meta">{meta_html}</div>
  {body}
  <section class="camp">
    <h2>📊 全部互动汇总</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>分组</th><th>推文数</th><th>总转发</th><th>总点赞</th><th>总回复</th></tr></thead>
      <tbody>{''.join(overall_rows)}</tbody>
    </table></div>
  </section>
  {analysis_html}
</body>
</html>"""


def main():
    # 路径：GHA / 本地可用 TWEET_DIR、OUTPUT_DIR 覆盖
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(script_dir, ".."))
    tweet_dir = os.environ.get("TWEET_DIR") or os.path.join(root, "raw")
    workspace_dir = os.environ.get("OUTPUT_DIR") or os.path.join(root, "site")
    tweet_dir = os.path.normpath(tweet_dir)
    workspace_dir = os.path.normpath(workspace_dir)

    print(f"=== gen_table.py — 推文表格生成器 ===")
    print(f"  推文目录: {tweet_dir}")
    print(f"  输出目录: {workspace_dir}")
    print()

    # 确保输出目录存在
    os.makedirs(workspace_dir, exist_ok=True)

    # 加载所有推文
    print("[STEP 1] 扫描 tweets_*.json 文件...")
    raw_records = load_tweets(tweet_dir)
    hours = hours_window()
    records, dropped = filter_by_hours_window(raw_records, hours)
    print(
        f"  [OK] 原始 {len(raw_records)} 条 → 时间窗 {hours}h 保留 {len(records)} 条"
        f"（丢弃 {dropped}）"
    )

    # 统计
    bloggers = set(r["screen_name"] for r in records)
    camps_seen = set(r["camp"] for r in records)
    if bloggers:
        print(f"  博主列表: {', '.join(sorted(bloggers))}")
    print()

    if not raw_records:
        print("[WARN] 未找到任何推文数据，仍写出空报告页")

    # 生成 JSON（空窗也写 []，保证页面可更新）
    print("[STEP 2] 生成 tweets_summary.json...")
    json_path = os.path.join(workspace_dir, "tweets_summary.json")
    # JSON 中只保留必要字段
    json_records = []
    for r in records:
        json_records.append({
            "camp": r["camp"],
            "camp_name": r["camp_name"],
            "screen_name": r["screen_name"],
            "display_name": r["display_name"],
            "created_at": r["created_at"],
            "id_str": r["id_str"],
            "full_text": r["full_text"],
            "full_text_en_200": r["full_text_en_200"],
            "summary": r["summary"],
            "retweet_count": r["retweet_count"],
            "favorite_count": r["favorite_count"],
            "reply_count": r["reply_count"],
            "hours_window": hours,
        })
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours_window": hours,
        "raw_count": len(raw_records),
        "kept_count": len(records),
        "dropped_count": dropped,
        "tweets": json_records,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  [OK] 已保存: {json_path} ({len(json_records)} records)")

    # 生成 HTML（Pages 入口用 index.html；另留 tweets_summary.html 兼容）
    print("[STEP 3] 生成 HTML...")
    html_content = generate_html(records, hours=hours)
    for name in ("index.html", "tweets_summary.html"):
        html_path = os.path.join(workspace_dir, name)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"  [OK] 已保存: {html_path}")

    print()
    print("=== 完成 ===")
    print(f"  总推文数: {len(records)}")
    print(f"  博主数: {len(bloggers)}")
    print(f"  阵营数: {len(camps_seen)}")
    print(f"  JSON: {json_path}")
    print(f"tweets_summary")

    return 0


if __name__ == "__main__":
    sys.exit(main())
