# Security policy

## Never commit

- WeChat ilink bot tokens or account IDs
- User openids
- OpenAI / GitHub / Slack API keys
- Chat transcripts, memory, logs, sessions, or backups
- A filled `config/bot.config.json` or `.env`

These are ignored by `.gitignore`. Run `python scripts/secret_scan.py` before
every push; CI runs it automatically.

## If a secret is exposed

1. Rotate the exposed credential immediately.
2. Remove it from the repository and history (for example, rewrite history
   with `git filter-repo`; a normal delete is not enough once pushed).
3. Audit the bot's `allow_from` and provider usage.
4. Do not post the secret in a public issue.

## Deployment hardening

- Set `allow_from` to the intended user IDs.
- Keep the API key in an environment variable, not in source.
- `mode = "yolo"` gives the agent full local permissions. Use a sandboxed mode,
  a dedicated machine, or a restricted account when possible.
- Treat `memory/` and backups as sensitive personal data.
- Run the health check and review logs after upgrades.

## Reporting

Please report vulnerabilities privately to the repository owner rather than in
a public issue. Do not include live credentials in the report.
