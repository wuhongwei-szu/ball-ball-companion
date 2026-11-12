param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Repo,
    [string]$Message = "Update companion tools"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Repo)) {
    throw "Repo not found: $Repo"
}
$toolsSrc = Join-Path $Source "tools"
$toolsDst = Join-Path $Repo "tools"
if (-not (Test-Path -LiteralPath $toolsSrc)) {
    throw "Source tools not found: $toolsSrc"
}
New-Item -ItemType Directory -Force -Path $toolsDst | Out-Null

$names = @(
    "common.py", "send_msg.py", "send_xi.py", "send_sticker.py",
    "send_tts.py", "send_voice.py", "chat_burst.py", "sticker_admin.py",
    "sticker_tag.py", "sticker_feedback.py", "sticker_review.py",
    "memory_search.py", "companion_memory.py", "capture_runtime.py",
    "capture_transcripts.py", "capture_review.py", "whoami.py",
    "view_session.py", "add_reminder.py", "reminder_admin.py",
    "care_scheduler.py", "care_timer_state.py", "reset_agent_threads.py",
    "learn_sticker.py", "healthcheck.py", "backup.ps1", "setup_tasks.ps1"
)
foreach ($name in $names) {
    $src = Join-Path $toolsSrc $name
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $toolsDst $name) -Force
    }
}

$wrapper = Join-Path $Source "bin\codex_wrapper.c"
if (Test-Path -LiteralPath $wrapper) {
    Copy-Item -LiteralPath $wrapper -Destination (Join-Path $Repo "deploy\codex_wrapper.c") -Force
}

Push-Location $Repo
try {
    python scripts\secret_scan.py
    if ($LASTEXITCODE -ne 0) {
        throw "Secret scan failed; refusing to commit."
    }

    git add -A
    $staged = @(git diff --cached --name-only)
    $allowed = '^(tools/|deploy/|docs/|prompts/|scripts/|config/.*example.*|README\.md$|CHANGELOG\.md$|\.gitignore$|LICENSE$|NOTICE\.md$|SECURITY\.md$|CONTRIBUTING\.md$|\.github/)'
    $unexpected = @($staged | Where-Object { $_ -and ($_ -notmatch $allowed) })
    if ($unexpected.Count -gt 0) {
        git reset | Out-Null
        throw ("Unexpected staged files; refusing to commit: " + ($unexpected -join ", "))
    }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Output "No changes to publish."
        return
    }

    git commit -m $Message
    git push
    Write-Output "Pushed: $Message"
} finally {
    Pop-Location
}
