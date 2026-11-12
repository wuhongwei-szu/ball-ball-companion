# cc-connect `/usage` Platform credit line

This patch keeps the existing cc-connect `/usage` output unchanged and appends
one line for OpenAI Platform usage:

```text
Platform 本月：usd 14.59 / Pro 额度 100.00，预计剩余 85.41
（额度刷新：预计每月14日，具体以 Platform 为准；数据更新 11-12 17:19）
```

## Base source

- cc-connect 1.5.0 maintained source digest
  `4251459e772d1a60d5df4dc4bcb0466c803863e1c29a9632374abff115cbcb6b`.
- Patch: `deploy/cc-connect-usage-balance.patch` (three files:
  `core/interfaces.go`, `core/engine.go`, `agent/codex/usage.go`).

## Apply and build

From a cc-connect source tree matching the base digest:

```bash
patch -p1 < deploy/cc-connect-usage-balance.patch
go build -mod=readonly -p=2 \
  -ldflags="-X main.version=1.5.0-usage-balance -X main.commit=local-usage-balance" \
  -o cc-connect-usage.exe ./cmd/cc-connect
```

Keep a copy of the original binary for rollback and verify the WeChat platforms
are `platform ready` after replacing it.

## Cache contract

The patch reads a JSON file named by `OPENAI_USAGE_CACHE`. Set it in the
launcher environment, for example:

```bat
set "OPENAI_USAGE_CACHE=C:\cc-weixin\memory\platform_usage.json"
```

`tools/usage_report.py` writes the cache (optionally every 30 minutes):

```json
{
  "cost": 14.5909,
  "credit": 100.0,
  "budget": 100.0,
  "remaining": 85.41,
  "currency": "usd",
  "credits_available": "",
  "refresh_day": "",
  "refresh_note": "预计每月14日，具体以 Platform 为准",
  "updated_at": "11-12 17:19",
  "error": ""
}
```

`budget` is kept for older caches; `credit` takes precedence. If `error` is
non-empty, `/usage` shows that error instead of a fabricated number.

## Credentials and limits

- Platform usage/costs require an **Admin key with `api.usage.read`**. A normal
  project API key returns HTTP 403.
- The official prepaid-credit balance endpoint needs a browser session key and
  expires; this patch deliberately does **not** store or scrape browser
  sessions. The displayed remaining value is an estimate
  (`Pro credit - month-to-date cost`), and Platform remains authoritative for
  the official balance.
- Never commit a real Admin key. Use a local `config/openai_admin.env` or
  environment variable; credentials are not printed by `usage_report.py`.