# cc-connect `/usage` UTC cost snapshot

The subscription quota/reset output stays unchanged. Platform costs now show
which UTC period was queried and the latest day with an actual monetary result.
Refreshing a cache is separate from receiving a new day's cost results.

```text
Platform 已返回费用：usd 25.00
UTC查询 [2026-11-01T00:00:00Z, 2026-11-13T16:30:00Z)；最后含金额结果日 2026-11-12；最后返回桶 2026-11-13；抓取 2026-11-13T16:30:00Z。空桶不证明已出账，未返回费用未计入。
配置参考额度 100.00；参考差额 75.00（非余额，未计未出账费用，账期未核对）
```

## API and date contract

The [official Costs API reference](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)
defines an inclusive `start_time`, exclusive `end_time`, daily buckets and
`has_more` / `next_page` pagination. The implementation queries from UTC midnight
on the first of the current UTC month to the query instant, and follows every
page. Local midnight is not used: it previously admitted the previous UTC day's
costs into a supposedly current-month total.

Buckets outside the requested start-day range are excluded. Identical overlapping
buckets are counted once; conflicting copies, malformed monetary data, mixed
currencies, failed pages and repeated/missing cursors reject the entire total.
No partial page sum is presented as the full query result.

`last_cost_date` is the latest UTC bucket containing a numeric monetary result,
including an explicit zero. `last_bucket_date` also includes empty buckets.
An empty bucket is not treated as a zero monetary result or evidence that its
day's costs have finished arriving. Neither date certifies that all prior costs
are final. A response with no monetary results says so instead of displaying
zero spend. Fetch time does not advance either date.

## Source and build

- The original feature patch remains `deploy/cc-connect-usage-balance.patch`.
- `deploy/cc-connect-usage-freshness.patch` is an incremental patch against the
  retained original-voice maintenance source (`maintained-source.zip`, release
  20261113-153928-original-voice), which already includes the original usage
  feature. Source archive SHA-256:
  `4ad0a0f5f033acad5460c0ff5fcb2f9271822221eb02c1847e332ee9f02f0f46`.
  It changes `core/interfaces.go`, the usage formatter in `core/engine.go`,
  five-language messages in `core/i18n.go`, `agent/codex/usage.go`, and two
  focused regression tests.
- Apply it to that exact maintained baseline, then run:

```bash
patch -p1 < deploy/cc-connect-usage-freshness.patch
go test -mod=readonly ./core ./agent/codex -run PlatformUsage
go build -mod=readonly -o cc-connect-usage.exe ./cmd/cc-connect
```

Do not replace an active binary as part of patch preparation. Preserve the
current executable, source, configuration and sessions for a separately
approved deployment. Updating the formatter first makes old caches visibly
require refresh; do not install the new Python producer with an old formatter
that interprets a null balance as zero.

## Version 2 cache

Set `OPENAI_USAGE_CACHE` to the local JSON cache. The Python producer writes it
atomically through the existing shared helper. This is an example with fixture
numbers, not a real account snapshot:

```json
{
  "version": 2,
  "cost": 25.0,
  "credit": 100.0,
  "budget": 100.0,
  "remaining": null,
  "reference_difference": 75.0,
  "currency": "usd",
  "period_start": "2026-11-01",
  "period_end": "2026-11-13",
  "period_timezone": "UTC",
  "query_start": "2026-11-01T00:00:00Z",
  "query_end": "2026-11-13T16:30:00Z",
  "last_cost_date": "2026-11-12",
  "last_bucket_date": "2026-11-13",
  "has_cost_results": true,
  "empty_buckets": 1,
  "pages": 2,
  "fetched_at": "2026-11-13T16:30:00Z",
  "credits_available": "",
  "error": ""
}
```

The formatter rejects legacy caches or contradictory/missing UTC metadata.
A nonempty `error` is displayed instead of money. Refresh failures therefore
cannot turn into an apparent zero cost or an increased balance. API response
bodies and raw exceptions are not copied into the public report/cache.

## Reference allowance and credentials

`OPENAI_PRO_CREDIT` (legacy aliases `OPENAI_MONTHLY_CREDIT` /
`OPENAI_MONTHLY_BUDGET`) is a locally configured reference amount. Its value
alone does not establish a grant, renewal time or matching billing cycle.
The UTC-calendar-month sum cannot establish a Pro billing-cycle balance.
`reference_difference` is only configured amount minus returned USD costs;
`remaining` is deliberately null. No reference difference is shown when there
are no monetary results or the returned currency is not USD.

Admin credentials remain in a private `config/openai_admin.env` or environment.
No real API calls are required for tests. The optional legacy credit endpoint is
separate and requires a sensitive browser session key; leave it unconfigured
unless specifically needed. No credentials or account records belong in patches.
