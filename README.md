# x-twitter-digest

独立仓库：定时采集 X/Twitter 名单 → 生成静态 HTML → 部署 GitHub Pages。

与 Kuroneko Agent / 微信推送无关；只做网页。

## 本地

```bash
# cookies: {"auth_token":"...","ct0":"..."}
export X_COOKIE_FILE=/path/to/cookies.json
export ZHIPU_API_KEY=...   # 可选

python scripts/run_collect.py
# 打开 site/index.html
```

改名单：编辑 `accounts.json`（`scripts/gen_table.py` 里 `CAMP_MAP` 建议同步）。

## GitHub

1. 新建空仓库，把本目录 push 上去  
2. Secrets：`X_COOKIES_JSON`（建议）、`ZHIPU_API_KEY`（可选）  
3. Settings → Pages → Source = **GitHub Actions**  
4. 跑 workflow **X Twitter Digest**（默认每 8 小时）

固定 URL 即最新摘要页；需要提醒时再另接 Server酱 / 本机微信 Bot 发链接。
