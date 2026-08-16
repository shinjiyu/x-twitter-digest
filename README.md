# x-twitter-digest

定时采集 X/Twitter → 静态 HTML → **GitHub Pages**，并像 [agent-harness-articles](https://github.com/shinjiyu/agent-harness-articles) 一样 **commit 归档**，历史不会丢。

## 行为

| 步骤 | 说明 |
|------|------|
| 采集 | `scripts/fetch_tweets.py`（cookie 优先，否则 guest） |
| 翻译 | **X 自带** `translations/show.json`（需 `X_COOKIES_JSON` 更稳） |
| 页面 | `site/index.html` = 最新 |
| 归档 | `site/archive/<UTC时间戳>/` + `site/archive/index.html` 列表，并 `git push` |

## 本地

```bash
export X_COOKIE_FILE=/path/to/cookies.json   # {"auth_token":"...","ct0":"..."}
python scripts/run_collect.py
python scripts/archive_site.py
# 打开 site/index.html 与 site/archive/
```

## GitHub

1. Secrets：`X_COOKIES_JSON`（强烈建议；guest 翻译常失败）
2. Pages → Source = **GitHub Actions**
3. Workflow **X Twitter Digest**（默认每 8 小时；也可手动）

在线最新：`https://<user>.github.io/x-twitter-digest/`  
历史：`.../archive/`
