# Contributing

Thanks for taking a look. This project is a small, personal-first companion
bot; keep changes focused and easy to review.

## Ground rules

- Never include personal data, tokens, openids, API keys, memory, logs, or
  backups in a commit.
- Keep `config/bot.config.json`, `.env`, `memory/`, `sessions/`, and `backups/`
  local and gitignored.
- Run the checks before opening a PR:

  ```bash
  python -m compileall tools scripts
  python scripts/secret_scan.py
  ```

- Update `CHANGELOG.md` for user-visible behavior changes.
- Update the relevant file in `docs/` when changing architecture, reminders,
  memory, or deployment.

## Style

- Python: standard library only; keep the scripts small and readable.
- PowerShell: parameters with safe defaults; no personal paths.
- Prompts/templates: use `{{PLACEHOLDER}}` syntax and no private details.
- The public repo contains only generic code and templates; private runtime
  files stay local.

## Syncing a private deployment

`scripts/sync_to_github.ps1` copies the reusable tools from a private work
directory into this repository, runs the secret scan, then commits and pushes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync_to_github.ps1 `
  -Source C:\ai-companion -Repo . -Message "Update companion tools"
```
