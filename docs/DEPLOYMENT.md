# Deployment

## Prerequisites

- Windows 10/11
- Python 3.11+
- Node.js 22+
- cc-connect 1.5.x (`npm install -g cc-connect@1.5.0`)
- Codex CLI (desktop MSIX or `npm install -g @openai/codex`)
- Two WeChat ilink bots
- An OpenAI API key

## 1. Work directory

Create a private work directory, for example `C:\ai-companion`, and clone or
copy this repository there. The repository is the public code; your private
runtime files live beside it (or in a separate clone).

## 2. cc-connect configuration

Copy `config/config.example.toml` to `%USERPROFILE%\.cc-connect\config.toml`.
Fill in:

- `work_dir` and `codex_home`
- `api_key` via `${OPENAI_API_KEY}`
- Two `[[projects.platforms]]` blocks with your bot tokens, account IDs, and
  `allow_from` openids
- Proxy settings if needed

Never commit the filled file.

## 3. Bot configuration

Copy `config/bot.config.example.json` to `config/bot.config.json` (gitignored)
and fill in:

- `work_dir`, `cc_data_dir`, `cc_config_file`
- `session_file` (find it under `%USERPROFILE%\.cc-connect\sessions\`; its name
  includes the work-dir hash)
- `master_session_id` / `xi_session_id` (normally `s1` / `s2`)
- `master_account_id` / `xi_account_id` (distinct stable bot accounts; list order is not identity)
- `bot_name` and labels

Do **not** put tokens or openids in this file. `common.py` reads them at
runtime from cc-connect's configuration and session file.

## 4. Prompts

Render `prompts/PERSONA.template.md` and `prompts/AGENTS.template.md` into
`PERSONA.md` and `AGENTS.md` in the work directory. Replace all `{{...}}`
placeholders.

## 5. Codex CLI on PATH

If `codex` is on PATH (npm CLI), no wrapper is needed. If you use the Windows
MSIX desktop build, its directory cannot be enumerated by `exec.LookPath`:

1. Build the small forwarder:

   ```bash
   gcc -O2 -o C:\ai-companion\bin\codex.exe deploy\codex_wrapper.c
   ```

2. Put `C:\ai-companion\bin` on PATH and set `CC_CODEX_REAL` to the real
   `codex.exe` path. The `deploy/start_cc.example.bat` template does both.

## 6. Startup and tasks

Copy `deploy/start_cc.example.bat` to `%USERPROFILE%\.cc-connect\start_cc.bat`
and adjust `BOT_ROOT`. Copy `deploy/start_cc_hidden.example.vbs` beside it.

Install the watchdog and daily backup:

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_tasks.ps1 -BotRoot C:\ai-companion
```

The watchdog runs every 5 minutes; the launcher itself skips when cc-connect
is already running. Backup runs daily at 04:17: Monday–Saturday produces a
light `cc-weixin-daily-*.zip` (memory/tools/config/sessions + sticker metadata),
and Sunday produces a full `cc-weixin-full-*.zip` (also assets images and the
cc-connect binary). Daily backups are kept 14 days, full backups 28 days, and
old legacy `cc-weixin-backup-*.zip` files keep the newest plus 7 days. Use
`backup.ps1 -Full` for a manual full backup.

## 7. Verify

```bash
python -X utf8 tools\healthcheck.py
```

Send a WeChat message to each bot. The first message from the second bot is
required before proactive messages to that user can work (WeChat ilink
`context_token` requirement).

## 8. Updating the public repository

Use the sync script from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync_to_github.ps1 `
  -Source C:\ai-companion -Repo . -Message "Update companion tools"
```

It copies only the reusable tools, runs the secret scan, then commits and
pushes. Never copy `config/bot.config.json`, `memory/`, logs, sessions, or
backups into the public repository.
