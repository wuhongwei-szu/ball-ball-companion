#!/usr/bin/env python3
"""Report subscription usage and UTC-month costs actually returned by Platform.

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
from decimal import Decimal
import json
import math
import os
import sys
import urllib.error
import urllib.parse
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
    for key in ("OPENAI_ADMIN_KEY", "OPENAI_MONTHLY_BUDGET", "OPENAI_SESSION_KEY",
                "OPENAI_PRO_CREDIT", "OPENAI_MONTHLY_CREDIT",
                "OPENAI_CREDIT_REFRESH_DAY", "OPENAI_CREDIT_REFRESH_NOTE"):
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


def fetch_platform_costs(admin_key, now=None):
    """Sum returned daily costs in the UTC calendar month, across every page.

    An empty bucket is not evidence that its day's bill is complete. The last
    bucket containing a numeric amount is reported separately from fetch time.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        return {"error": "Platform costs requires an aware query time"}
    now = now.astimezone(datetime.timezone.utc).replace(microsecond=0)
    start = now.replace(day=1, hour=0, minute=0, second=0)
    params = {"start_time": int(start.timestamp()), "end_time": int(now.timestamp()),
              "bucket_width": "1d", "limit": 31}
    total = Decimal(0)
    currency = None
    seen_buckets, seen_pages = {}, set()
    dates, cost_dates = [], []
    empty = excluded = pages = 0
    try:
        while True:
            pages += 1
            if pages > 100:
                raise ValueError("pagination_limit")
            payload = _request_json(ORG_COSTS_URL + "?" + urllib.parse.urlencode(params),
                                    {"Authorization": "Bearer " + admin_key})
            if (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)
                    or type(payload.get("has_more")) is not bool):
                raise ValueError("invalid_page")
            for bucket in payload["data"]:
                lo, hi = bucket.get("start_time"), bucket.get("end_time")
                if type(lo) is not int or type(hi) is not int or hi <= lo:
                    raise ValueError("invalid_bucket")
                if lo < params["start_time"] or lo >= params["end_time"]:
                    excluded += 1
                    continue
                key = (lo, hi)
                signature = json.dumps(bucket, sort_keys=True, allow_nan=False)
                if key in seen_buckets:
                    if seen_buckets[key] != signature:
                        raise ValueError("conflicting_bucket")
                    continue
                seen_buckets[key] = signature
                results = bucket.get("results")
                if not isinstance(results, list):
                    raise ValueError("invalid_results")
                day = datetime.datetime.fromtimestamp(lo, datetime.timezone.utc).date().isoformat()
                dates.append(day)
                if not results:
                    empty += 1
                for item in results:
                    amount = item.get("amount")
                    if not isinstance(amount, dict) or type(amount.get("value")) not in (int, float):
                        raise ValueError("invalid_amount")
                    value = Decimal(str(amount["value"]))
                    unit = amount.get("currency") or "usd"
                    if not value.is_finite() or not isinstance(unit, str):
                        raise ValueError("invalid_amount")
                    unit = unit.lower()
                    if currency is not None and currency != unit:
                        raise ValueError("mixed_currency")
                    currency = unit
                    total += value
                    cost_dates.append(day)
            if not payload["has_more"]:
                break
            cursor = payload.get("next_page")
            if not isinstance(cursor, str) or not cursor or cursor in seen_pages:
                raise ValueError("invalid_pagination")
            seen_pages.add(cursor)
            params["page"] = cursor
    except urllib.error.HTTPError as exc:
        # Response bodies and raw exceptions may contain private diagnostics.
        code = exc.code
        exc.close()
        return {"error": f"Platform costs HTTP {code}"}
    except Exception as exc:
        return {"error": f"Platform costs {type(exc).__name__}"}
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    return {"cost": float(total.quantize(Decimal("0.0001"))), "currency": currency or "usd",
            "period_start": start.strftime("%Y-%m-%d"),
            "period_end": now.strftime("%Y-%m-%d"), "period_timezone": "UTC",
            "query_start": stamp(start), "query_end": stamp(now), "fetched_at": stamp(now),
            "last_cost_date": max(cost_dates) if cost_dates else None,
            "last_bucket_date": max(dates) if dates else None,
            "has_cost_results": bool(cost_dates), "empty_buckets": empty,
            "excluded_buckets": excluded, "pages": pages}


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
        "version": 2,
        "cost": platform.get("cost"),
        "credit": platform.get("credit", platform.get("budget")),
        "budget": platform.get("budget"),
        "remaining": platform.get("remaining"),
        "reference_difference": platform.get("reference_difference"),
        "currency": platform.get("currency", "usd"),
        "period_start": platform.get("period_start"),
        "period_end": platform.get("period_end"),
        **{key: platform.get(key) for key in (
            "period_timezone", "query_start", "query_end", "fetched_at",
            "last_cost_date", "last_bucket_date", "has_cost_results",
            "empty_buckets", "excluded_buckets", "pages")},
        "credits_available": "" if available is None else str(available),
        "refresh_day": platform.get("refresh_day", ""),
        "refresh_note": platform.get("refresh_note", ""),
        "updated_at": datetime.datetime.now().astimezone().strftime("%m-%d %H:%M"),
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
        credit = float(cfg.get("OPENAI_PRO_CREDIT")
                       or cfg.get("OPENAI_MONTHLY_CREDIT")
                       or cfg.get("OPENAI_MONTHLY_BUDGET")
                       or "100")
    except (ValueError, TypeError):
        credit = None
    if credit is not None and (not math.isfinite(credit) or credit < 0):
        credit = None
    refresh_day = str(cfg.get("OPENAI_CREDIT_REFRESH_DAY", "")).strip()
    refresh_note = str(cfg.get("OPENAI_CREDIT_REFRESH_NOTE", "")).strip()
    if "cost" in platform:
        platform["credit"] = round(credit, 2) if credit is not None else None
        platform["budget"] = platform["credit"]  # legacy cache key
        # Calendar-month costs do not establish a subscription grant's billing
        # cycle or remaining balance. Keep only an explicitly labeled reference.
        platform["remaining"] = None
        platform["reference_difference"] = (
            round(credit - platform["cost"], 2)
            if credit is not None and platform.get("has_cost_results")
            and platform.get("currency") == "usd" else None)
        if refresh_note:
            platform["refresh_day"] = ""
            platform["refresh_note"] = refresh_note
        else:
            platform["refresh_day"] = refresh_day
            platform["refresh_note"] = ""
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
        refresh = ""
        if plat.get("refresh_day"):
            refresh = "；配置刷新日：每月%s日" % plat["refresh_day"]
        elif plat.get("refresh_note"):
            refresh = "；配置刷新说明：%s" % plat["refresh_note"]
        amount = ("%s %.2f" % (plat.get("currency", "usd"), plat["cost"])
                  if plat.get("has_cost_results") else "暂无金额结果（不能确认零花费）")
        lines.append("Platform API 已返回费用：%s；UTC查询 [%s, %s)"
                     % (amount, plat.get("query_start", ""), plat.get("query_end", "")))
        lines.append("最后含金额结果日：%s UTC；最后返回桶：%s UTC；抓取：%s。空桶不证明已出账，未返回费用未计入。"
                     % (plat.get("last_cost_date") or "无", plat.get("last_bucket_date") or "无",
                        plat.get("fetched_at", "")))
        if plat.get("reference_difference") is not None:
            lines.append("配置参考额度 %.2f；参考差额 %.2f（非余额，未计未出账费用；账期未核对%s）"
                         % (plat.get("credit", 0), plat["reference_difference"], refresh))
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
