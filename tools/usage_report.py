#!/usr/bin/env python3
"""Report ChatGPT subscription usage plus OpenAI Platform API spend/budget.

Why this exists:
- cc-connect's `/usage` calls the ChatGPT OAuth endpoint
  `chatgpt.com/backend-api/wham/usage`; that is the ChatGPT subscription
  quota/reset/credits view, not Platform API billing.
- The Platform organization usage/costs API requires an Admin key with the
  `api.usage.read` scope. The normal project API key returns HTTP 403.
- The legacy remaining-credit endpoint requires a browser session key, so this
  tool treats it as optional and never prints either credential.

Configuration (never commit real keys):
    OPENAI_ADMIN_KEY=sk-admin-...          # or put it in config/openai_admin.env
    OPENAI_MONTHLY_BUDGET=100
    OPENAI_SESSION_KEY=...                 # optional browser session key

Usage:
    python -X utf8 tools/usage_report.py
    python -X utf8 tools/usage_report.py --json
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import common as c
    ROOT = Path(c.WORK_DIR)
    DEFAULT_PROXY = c.CFG.get("proxy", "")
except Exception:
    c = None
    ROOT = Path(__file__).resolve().parents[1]
    DEFAULT_PROXY = ""

CHATGPT_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
ORG_COSTS_URL = "https://api.openai.com/v1/organization/costs"
CREDIT_GRANTS_URL = "https://api.openai.com/dashboard/billing/credit_grants"
CACHE_PATH = Path(ROOT) / "memory" / "platform_usage.json"


def _auth_paths():
    paths = []
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        paths.append(Path(codex_home) / "auth.json")
    paths.append(Path.home() / ".codex" / "auth.json")
    paths.append(ROOT / ".codex" / "auth.json")
    return paths


def _load_env_file(path):
    data = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return data


def _config():
    merged = {}
    for path in (Path.home() / ".cc-connect" / "openai_admin.env",
                 ROOT / "config" / "openai_admin.env"):
        merged.update(_load_env_file(path))
    for key in ("OPENAI_ADMIN_KEY", "OPENAI_MONTHLY_BUDGET", "OPENAI_SESSION_KEY"):
        if os.environ.get(key):
            merged[key] = os.environ[key]
    return merged


def _opener():
    proxy = os.environ.get("HTTPS_PROXY") or DEFAULT_PROXY
    if proxy:
        os.environ.setdefault("HTTPS_PROXY", proxy)
        os.environ.setdefault("HTTP_PROXY", proxy)
    return urllib.request.build_opener()


def _request_json(url, headers, timeout=30):
    req = urllib.request.Request(url, headers=headers)
    with _opener().open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_chatgpt_usage():
    token = ""
    account = ""
    for path in _auth_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        tokens = data.get("tokens") or {}
        if tokens.get("access_token"):
            token = tokens["access_token"]
            account = tokens.get("account_id", "")
            break
    if not token:
        return {"error": "找不到 ChatGPT OAuth auth.json（tokens.access_token）"}
    try:
        payload = _request_json(CHATGPT_USAGE_URL, {
            "Authorization": "Bearer " + token,
            "ChatGPT-Account-Id": account,
            "User-Agent": "codex-cli",
        })
    except urllib.error.HTTPError as exc:
        return {"error": f"ChatGPT usage HTTP {exc.code}"}
    except Exception as exc:
        return {"error": f"ChatGPT usage {type(exc).__name__}"}
    rate = payload.get("rate_limit") or {}
    window = rate.get("primary_window") or {}
    credits = payload.get("credits") or {}
    reset_at = window.get("reset_at")
    reset_text = ""
    if isinstance(reset_at, (int, float)) and reset_at > 0:
        reset_text = datetime.datetime.fromtimestamp(reset_at).astimezone().strftime("%Y-%m-%d %H:%M")
    return {
        "plan": payload.get("plan_type", ""),
        "used_percent": window.get("used_percent"),
        "reset_at": reset_text,
        "reset_after_seconds": window.get("reset_after_seconds"),
        "credits_balance": credits.get("balance"),
        "has_credits": credits.get("has_credits"),
    }


def fetch_platform_costs(admin_key):
    now = datetime.datetime.now().astimezone()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    url = (ORG_COSTS_URL + "?start_time=%d&end_time=%d&bucket_width=1d&limit=31"
           % (int(start.timestamp()), int(now.timestamp())))
    try:
        payload = _request_json(url, {"Authorization": "Bearer " + admin_key})
    except urllib.error.HTTPError as exc:
        body = exc.read(300).decode("utf-8", "replace")
        return {"error": f"Platform costs HTTP {exc.code}: {body[:200]}"}
    except Exception as exc:
        return {"error": f"Platform costs {type(exc).__name__}: {exc}"}
    total = 0.0
    currency = "usd"
    for bucket in payload.get("data") or []:
        for item in bucket.get("results") or []:
            amount = item.get("amount") or {}
            value = amount.get("value")
            if isinstance(value, (int, float)):
                total += float(value)
            currency = amount.get("currency", currency)
    return {"cost": round(total, 4), "currency": currency,
            "period_start": start.strftime("%Y-%m-%d"),
            "period_end": now.strftime("%Y-%m-%d")}


def fetch_credit_grants(session_key):
    try:
        payload = _request_json(CREDIT_GRANTS_URL, {"Authorization": "Bearer " + session_key})
    except urllib.error.HTTPError as exc:
        return {"error": f"Credit grants HTTP {exc.code}"}
    except Exception as exc:
        return {"error": f"Credit grants {type(exc).__name__}"}
    return {k: payload.get(k) for k in ("total_granted", "total_used", "total_available")}


def _write_cache(report):
    """Write the small cache read by cc-connect's /usage line."""
    platform = report.get("platform", {})
    credits = report.get("credit_grants", {}) or {}
    available = credits.get("total_available")
    payload = {
        "cost": platform.get("cost"),
        "budget": platform.get("budget"),
        "remaining": platform.get("remaining"),
        "currency": platform.get("currency", "usd"),
        "period_start": platform.get("period_start"),
        "period_end": platform.get("period_end"),
        "credits_available": "" if available is None else str(available),
        "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "error": platform.get("error", ""),
    }
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if c is not None and hasattr(c, "save_json_atomic"):
            c.save_json_atomic(str(CACHE_PATH), payload)
        else:
            CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    except Exception as exc:
        print(f"[usage] cache write failed: {exc}", file=sys.stderr)


def build_report():
    cfg = _config()
    chatgpt = fetch_chatgpt_usage()
    admin_key = cfg.get("OPENAI_ADMIN_KEY", "")
    platform = fetch_platform_costs(admin_key) if admin_key else {
        "error": "未配置 OPENAI_ADMIN_KEY（Platform 需要 api.usage.read 的 Admin key）"
    }
    try:
        budget = float(cfg.get("OPENAI_MONTHLY_BUDGET", "100"))
    except ValueError:
        budget = 100.0
    if "cost" in platform:
        platform["budget"] = round(budget, 2)
        platform["remaining"] = round(budget - platform["cost"], 2)
    session_key = cfg.get("OPENAI_SESSION_KEY", "")
    credits = fetch_credit_grants(session_key) if session_key else {"error": "未配置可选 OPENAI_SESSION_KEY"}
    report = {"chatgpt": chatgpt, "platform": platform, "credit_grants": credits}
    _write_cache(report)
    return report


def format_text(report):
    lines = []
    chat = report["chatgpt"]
    if "error" in chat:
        lines.append("ChatGPT 订阅用量：不可用（%s）" % chat["error"])
    else:
        reset = chat.get("reset_at") or "未知"
        hours = chat.get("reset_after_seconds")
        extra = ("，约 %.1f 小时" % (hours / 3600)) if isinstance(hours, (int, float)) else ""
        lines.append("ChatGPT 订阅：plan=%s，窗口已用 %s%%，重置 %s%s"
                     % (chat.get("plan", ""), chat.get("used_percent", "?"), reset, extra))
        lines.append("ChatGPT credits：%s（has_credits=%s）"
                     % (chat.get("credits_balance", "?"), chat.get("has_credits", "?")))
    plat = report["platform"]
    if "cost" in plat:
        lines.append("Platform API 本月：%s %.2f / 预算 %.2f，剩余 %.2f（%s—%s）"
                     % (plat.get("currency", "usd"), plat["cost"], plat.get("budget", 0),
                        plat.get("remaining", 0), plat.get("period_start", ""), plat.get("period_end", "")))
    else:
        lines.append("Platform API 本月：不可用（%s）" % plat.get("error", "unknown"))
    credits = report["credit_grants"]
    if "total_available" in credits:
        lines.append("Platform credits：可用 %s / 已用 %s / 总额 %s"
                     % (credits.get("total_available"), credits.get("total_used"), credits.get("total_granted")))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ChatGPT + Platform API usage report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())