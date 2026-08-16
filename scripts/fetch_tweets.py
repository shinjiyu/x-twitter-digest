#!/usr/bin/env python3
"""
Fetch recent tweets for a given X/Twitter screen_name using GraphQL API.
Uses cookie authentication (auth_token + ct0) from keychain file as primary,
falls back to guest token if cookies fail.

Cookie file path is read from environment variable X_COOKIE_FILE or defaults to
/data/vault/blocks/keychain/entries/twitter_x_cookies.json

Usage: python3 fetch_tweets.py <screen_name> [count]
Output: JSON file at .run/ew/test_fetch.json (overridable via OUTPUT_FILE env)
"""

import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# === Constants ===
BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
GUEST_BEARER = "AAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

USER_BY_SCREEN_NAME_QUERY_ID = "sLVLhk0bGj3MVFEKTdax1w"
USER_TWEETS_QUERY_ID = "E3opETHurmVJflFsUBVuUQ"

API_BASE = "https://api.twitter.com/graphql"
GUEST_ACTIVATE_URL = "https://api.twitter.com/1.1/guest/activate.json"

# Features JSON (verified working set from peer workspace)
FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

# Additional features for UserByScreenName
USER_FEATURES = {
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

SSL_CTX = ssl._create_unverified_context()


def load_cookies():
    """Load cookies from keychain file. Returns dict with auth_token, ct0, and cookie_string."""
    cookie_file = os.environ.get("X_COOKIE_FILE",
                                  "/data/vault/blocks/keychain/entries/twitter_x_cookies.json")
    if not os.path.exists(cookie_file):
        # Try alternate file
        alt_file = "/data/vault/blocks/keychain/entries/x_cookie.json"
        if os.path.exists(alt_file):
            cookie_file = alt_file
        else:
            return None, cookie_file

    with open(cookie_file, "r") as f:
        raw = f.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, cookie_file

    # Handle keychain wrapper format: {key, kind, value, ...}
    if isinstance(data, dict) and "value" in data and "key" in data:
        val = data["value"]
        if isinstance(val, str):
            # value might be a cookie string "auth_token=xxx; ct0=yyy"
            # or a JSON string
            try:
                val_parsed = json.loads(val)
                data = val_parsed
            except (json.JSONDecodeError, ValueError):
                # It's a plain cookie string
                cookies_dict = {}
                for part in val.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        cookies_dict[k.strip()] = v.strip()
                auth_token = cookies_dict.get("auth_token")
                ct0 = cookies_dict.get("ct0")
                if not auth_token or not ct0:
                    return None, cookie_file
                cookie_string = val if val.startswith("auth_token=") else "; ".join(
                    f"{k}={v}" for k, v in cookies_dict.items()
                )
                return {"auth_token": auth_token, "ct0": ct0, "cookie_string": cookie_string}, cookie_file
        elif isinstance(val, (dict, list)):
            data = val
        else:
            return None, cookie_file

    auth_token = None
    ct0 = None
    cookies_dict = {}

    if isinstance(data, dict):
        # Could be {"cookies": [...]} or flat {"auth_token": "...", "ct0": "..."}
        if "cookies" in data and isinstance(data["cookies"], list):
            for c in data["cookies"]:
                name = c.get("name", "")
                value = c.get("value", "")
                cookies_dict[name] = value
        else:
            cookies_dict = data
    elif isinstance(data, list):
        for c in data:
            name = c.get("name", "")
            value = c.get("value", "")
            cookies_dict[name] = value

    auth_token = cookies_dict.get("auth_token")
    ct0 = cookies_dict.get("ct0")

    if not auth_token or not ct0:
        return None, cookie_file

    # Build cookie string - include all cookies we have
    cookie_parts = []
    for k, v in cookies_dict.items():
        if v and k not in ("path", "domain", "expires", "secure", "httpOnly", "sameSite"):
            cookie_parts.append(f"{k}={v}")
    cookie_string = "; ".join(cookie_parts)

    return {"auth_token": auth_token, "ct0": ct0, "cookie_string": cookie_string}, cookie_file


def get_guest_token():
    """Get a guest token for unauthenticated access."""
    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    req = urllib.request.Request(GUEST_ACTIVATE_URL, method="POST", headers=headers, data=b"")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("guest_token")
    except Exception as e:
        print(f"  [WARN] Guest token failed: {e}", file=sys.stderr)
        return None


def make_request(url, headers, max_retries=2):
    """Make HTTP request with retry on 429."""
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500] if e.fp else ""
            if e.code == 429 and attempt < max_retries:
                print(f"  [WARN] HTTP 429 rate limited, waiting 10s (attempt {attempt+1})", file=sys.stderr)
                time.sleep(10)
                continue
            print(f"  [ERROR] HTTP {e.code}: {body}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  [ERROR] Request failed: {e}", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(3)
                continue
            return None
    return None


def get_user_id(screen_name, cookies=None, guest_token=None):
    """Resolve screen_name to user_id via UserByScreenName GraphQL."""
    variables = {
        "screen_name": screen_name,
        "withSafetyModeUserFields": True,
    }
    features_str = urllib.parse.quote(json.dumps(USER_FEATURES), safe="")
    variables_str = urllib.parse.quote(json.dumps(variables), safe="")

    url = f"{API_BASE}/{USER_BY_SCREEN_NAME_QUERY_ID}/UserByScreenName?variables={variables_str}&features={features_str}"

    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": f"https://x.com/{screen_name}",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
    }

    if cookies:
        headers["Cookie"] = cookies["cookie_string"]
        headers["x-csrf-token"] = cookies["ct0"]
    elif guest_token:
        headers["x-guest-token"] = guest_token

    data = make_request(url, headers)
    if not data:
        return None, None

    try:
        user_result = data["data"]["user"]["result"]
        user_id = user_result.get("rest_id")
        # Also get legacy info
        legacy = user_result.get("legacy", {})
        name = legacy.get("name", screen_name)
        return user_id, {"name": name, "screen_name": screen_name, "rest_id": user_id}
    except (KeyError, TypeError) as e:
        print(f"  [ERROR] Failed to parse user data: {e}", file=sys.stderr)
        print(f"  [DEBUG] Response keys: {list(data.get('data', {}).keys()) if data else 'None'}", file=sys.stderr)
        return None, None


def get_user_tweets(user_id, count=20, cookies=None, guest_token=None):
    """Fetch recent tweets via UserTweets GraphQL."""
    variables = {
        "userId": user_id,
        "count": count,
        "includePromotedContent": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withVoice": True,
        "withV2Timeline": True,
    }
    features_str = urllib.parse.quote(json.dumps(FEATURES), safe="")
    variables_str = urllib.parse.quote(json.dumps(variables), safe="")

    url = f"{API_BASE}/{USER_TWEETS_QUERY_ID}/UserTweets?variables={variables_str}&features={features_str}"

    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": f"https://x.com/",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
    }

    if cookies:
        headers["Cookie"] = cookies["cookie_string"]
        headers["x-csrf-token"] = cookies["ct0"]
    elif guest_token:
        headers["x-guest-token"] = guest_token

    data = make_request(url, headers, max_retries=3)
    return data


def extract_tweets(response):
    """Extract tweets from UserTweets response following the verified extraction path."""
    tweets = []
    if not response or "data" not in response:
        return tweets

    try:
        instructions = response["data"]["user"]["result"]["timeline_v2"]["timeline"]["instructions"]
    except (KeyError, TypeError):
        print("  [WARN] Could not find timeline_v2 in response", file=sys.stderr)
        return tweets

    for instruction in instructions:
        if instruction.get("type") != "TimelineAddEntries":
            continue
        entries = instruction.get("entries", [])
        for entry in entries:
            content = entry.get("content", {})
            entry_type = content.get("entryType", "")
            # Skip cursor entries
            if entry_type.startswith("TimelineTimelineCursor"):
                continue
            if entry_type != "TimelineTimelineItem":
                continue

            try:
                tweet_results = content["itemContent"]["tweet_results"]["result"]
            except (KeyError, TypeError):
                continue

            # Handle TweetWithVisibilityResults
            if isinstance(tweet_results, dict):
                typename = tweet_results.get("__typename", "")
                if typename == "TweetTombstone":
                    continue
                if typename == "TweetWithVisibilityResults":
                    tweet_obj = tweet_results.get("tweet", tweet_results)
                else:
                    tweet_obj = tweet_results
            else:
                continue

            legacy = tweet_obj.get("legacy", {})
            # Get full text - prefer note_tweet for long-form
            note_tweet = tweet_obj.get("note_tweet", {})
            full_text = ""
            if note_tweet:
                try:
                    full_text = note_tweet["note_tweet_results"]["result"]["text"]
                except (KeyError, TypeError):
                    full_text = legacy.get("full_text", "")
            else:
                full_text = legacy.get("full_text", "")

            tweet_id = tweet_obj.get("rest_id") or legacy.get("id_str", "")
            created_at = legacy.get("created_at", "")

            tweets.append({
                "id_str": tweet_id,
                "created_at": created_at,
                "full_text": full_text,
                "retweet_count": legacy.get("retweet_count", 0),
                "favorite_count": legacy.get("favorite_count", 0),
                "reply_count": legacy.get("reply_count", 0),
                "quote_count": legacy.get("quote_count", 0),
                "lang": legacy.get("lang", ""),
            })

    return tweets


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_tweets.py <screen_name> [count]", file=sys.stderr)
        sys.exit(1)

    screen_name = sys.argv[1].lstrip("@")
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    default_out = os.path.join(
        os.environ.get("TWEET_DIR", ".run/ew"), f"tweets_{screen_name}.json"
    )
    output_file = os.environ.get("OUTPUT_FILE", default_out)

    print(f"=== Fetching tweets for @{screen_name} (count={count}) ===")

    # Step 1: Try cookie authentication
    cookies, cookie_file = load_cookies()
    auth_mode = None

    if cookies:
        print(f"  [INFO] Loaded cookies from {cookie_file}")
        auth_mode = "cookie"
    else:
        print(f"  [INFO] No valid cookies found at {cookie_file}")
        print(f"  [INFO] Falling back to guest token...")
        guest_token = get_guest_token()
        if guest_token:
            print(f"  [INFO] Got guest token: {guest_token[:10]}...")
            auth_mode = "guest"
        else:
            print("  [ERROR] No authentication method available", file=sys.stderr)
            sys.exit(1)

    # Step 2: Resolve screen_name to user_id
    print(f"  [STEP 1] Resolving @{screen_name} to user_id...")
    if auth_mode == "cookie":
        user_id, user_info = get_user_id(screen_name, cookies=cookies)
    else:
        user_id, user_info = get_user_id(screen_name, guest_token=guest_token)

    if not user_id:
        # If cookie auth failed, try guest token
        if auth_mode == "cookie":
            print("  [WARN] Cookie auth failed for UserByScreenName, trying guest token...")
            guest_token = get_guest_token()
            if guest_token:
                user_id, user_info = get_user_id(screen_name, guest_token=guest_token)
                if user_id:
                    auth_mode = "guest"

    if not user_id:
        print(f"  [ERROR] Could not resolve user_id for @{screen_name}", file=sys.stderr)
        result = {
            "screen_name": screen_name,
            "error": "Could not resolve user_id",
            "user_id": None,
            "tweets": [],
            "auth_mode": auth_mode,
        }
        out_dir = os.path.dirname(output_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  [INFO] Saved error result to {output_file}")
        sys.exit(1)

    print(f"  [OK] user_id = {user_id} ({user_info.get('name', '')})")

    # Step 3: Fetch tweets
    print(f"  [STEP 2] Fetching {count} tweets...")
    if auth_mode == "cookie":
        tweets_data = get_user_tweets(user_id, count=count, cookies=cookies)
    else:
        tweets_data = get_user_tweets(user_id, count=count, guest_token=guest_token)

    if not tweets_data:
        # Try fallback with guest token if cookie failed
        if auth_mode == "cookie":
            print("  [WARN] Cookie auth failed for UserTweets, trying guest token...")
            guest_token = get_guest_token()
            if guest_token:
                tweets_data = get_user_tweets(user_id, count=count, guest_token=guest_token)
                if tweets_data:
                    auth_mode = "guest"

    if not tweets_data:
        print(f"  [ERROR] Failed to fetch tweets", file=sys.stderr)
        result = {
            "screen_name": screen_name,
            "user_id": user_id,
            "error": "Failed to fetch tweets",
            "tweets": [],
            "auth_mode": auth_mode,
        }
    else:
        tweets = extract_tweets(tweets_data)
        print(f"  [OK] Extracted {len(tweets)} tweets")

        # Save raw response for debugging
        raw_file = output_file.replace(".json", "_raw.json")
        raw_dir = os.path.dirname(raw_file)
        if raw_dir:
            os.makedirs(raw_dir, exist_ok=True)
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(tweets_data, f, ensure_ascii=False, indent=2)
        print(f"  [INFO] Raw response saved to {raw_file}")

        result = {
            "screen_name": screen_name,
            "user_id": user_id,
            "user_name": user_info.get("name", ""),
            "error": None,
            "tweet_count": len(tweets),
            "auth_mode": auth_mode,
            "tweets": tweets[:count],
        }

    # Step 4: Save result
    out_dir = os.path.dirname(output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  [DONE] Saved {len(result['tweets'])} tweets to {output_file}")
    print(f"  [INFO] Auth mode: {auth_mode}")

    # Print summary
    print("\n=== Summary ===")
    print(f"  Screen name: @{screen_name}")
    print(f"  User ID: {user_id}")
    print(f"  Auth mode: {auth_mode}")
    print(f"  Tweets fetched: {len(result['tweets'])}")

    if result['tweets']:
        print(f"Fetched {len(result['tweets'])} tweets for @{screen_name}")
    for i, tw in enumerate(result["tweets"][:5], 1):
        text_preview = tw["full_text"][:80].replace("\n", " ") + "..." if len(tw["full_text"]) > 80 else tw["full_text"].replace("\n", " ")
        print(f"  {i}. [{tw['created_at']}] {text_preview}")

    print(f"\nDONE: saved to {output_file}")


if __name__ == "__main__":
    main()
