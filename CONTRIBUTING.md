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
  python -m pip install -r requirements.txt
  python -m compileall tools scripts
  python -m unittest discover -s tests -v
  python scripts/secret_scan.py
  ```

- Update `CHANGELOG.md` for user-visible behavior changes.
- Update the relevant file in `docs/` when changing architecture, reminders,
  memory, or deployment.

## Style

- Prefer the Python standard library for orchestration. Reuse maintained SDKs
  and codecs for model/media boundaries; declare dependencies in
  `requirements.txt` and keep scripts small and readable.
- PowerShell: parameters with safe defaults; no personal paths.
- Prompts/templates: use `{{PLACEHOLDER}}` syntax and no private details.
- The public repo contains only generic code and templates; private runtime
  files stay local.

## Syncing a private deployment

`scripts/sync_to_github.ps1` copies the reusable tools from a private work
directory into this repository and runs the secret scan. By default it only
prepares working-tree changes for review:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync_to_github.ps1 `
  -Source C:\ai-companion -Repo . -Message "Update companion tools"
```

To publish the reviewed reusable files, add `-Publish` explicitly. The script
refuses a nonempty index or conflicting local edits, stages only its file list,
scans the exact index and stops when Git fails. Private deployment checks and
conversation-specific reports belong in ignored local artifacts.

## Versions

Keep user-visible changes in `CHANGELOG.md`. Update the README version link,
commit the reviewed source, and wait for the commit's CI checks before creating
an annotated version tag and matching GitHub Release. Use a minor version for
new functionality and a patch version for compatible fixes. Do not move an
existing published tag or attach private binaries, data or maintenance archives.
