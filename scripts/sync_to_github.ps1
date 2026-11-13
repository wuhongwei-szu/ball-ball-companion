param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Repo,
    [string]$Message = "Update companion tools",
    [switch]$Publish
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Repo)) {
    throw "Repo not found: $Repo"
}
$Source = (Resolve-Path -LiteralPath $Source).Path
$toolsSrc = Join-Path $Source "tools"
if (-not (Test-Path -LiteralPath $toolsSrc)) {
    throw "Source tools not found: $toolsSrc"
}
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$copies = [System.Collections.Generic.List[object]]::new()

function Add-PublicSource([string]$src, [string]$relative) {
    if (Test-Path -LiteralPath $src -PathType Leaf) {
        $copies.Add([pscustomobject]@{ Source = $src; Relative = $relative })
    }
}

$names = @(
    "common.py", "local_state.py", "send_msg.py", "send_xi.py", "send_sticker.py",
    "send_tts.py", "send_voice.py", "listen_audio.py", "chat_burst.py", "sticker_admin.py",
    "sticker_tag.py", "sticker_feedback.py", "sticker_review.py",
    "memory_search.py", "companion_memory.py", "capture_runtime.py",
    "capture_transcripts.py", "capture_review.py", "whoami.py",
    "view_session.py", "add_reminder.py", "reminder_admin.py",
    "care_scheduler.py", "care_timer_state.py", "reset_agent_threads.py",
    "learn_sticker.py", "healthcheck.py", "backup.ps1", "setup_tasks.ps1",
    "usage_report.py"
)
foreach ($name in $names) {
    $src = Join-Path $toolsSrc $name
    Add-PublicSource $src ("tools/" + $name)
}
foreach ($name in @('requirements.txt')) {
    Add-PublicSource (Join-Path $Source $name) $name
}

$wrapper = Join-Path $Source "bin\codex_wrapper.c"
Add-PublicSource $wrapper "deploy/codex_wrapper.c"

$configExample = Join-Path $Source "config\openai_admin.env.example"
Add-PublicSource $configExample "config/openai_admin.env.example"
$coreExample = Join-Path $Source "config\core_memory.example.json"
Add-PublicSource $coreExample "config/core_memory.example.json"
$usagePatch = Join-Path $Source "maintenance\releases\20261112-usage-balance\cc-connect-usage-balance.patch"
Add-PublicSource $usagePatch "deploy/cc-connect-usage-balance.patch"

Push-Location $Repo
try {
    $top = git rev-parse --show-toplevel
    if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath($top) -ne $Repo) { throw "Repo must be a Git work-tree root." }
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) { throw "Index must be empty; preserve or commit existing staged work first." }
    if ($copies.Count -eq 0) { throw "No reusable source files found." }
    # Check every destination before copying so local edits survive a rejected sync.
    foreach ($copy in $copies) {
        $dst = Join-Path $Repo $copy.Relative
        $dirty = @(git status --porcelain -- $copy.Relative)
        if ($LASTEXITCODE -ne 0) { throw "Cannot inspect destination state." }
        if ($dirty.Count -gt 0 -and ((-not (Test-Path -LiteralPath $dst -PathType Leaf)) -or
            ((Get-FileHash -LiteralPath $copy.Source).Hash -ne (Get-FileHash -LiteralPath $dst).Hash))) {
            throw ("Refusing to overwrite local edits: " + $copy.Relative)
        }
    }
    foreach ($copy in $copies) {
        $dst = Join-Path $Repo $copy.Relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        if ([IO.Path]::GetFullPath($copy.Source) -ne [IO.Path]::GetFullPath($dst)) {
            Copy-Item -LiteralPath $copy.Source -Destination $dst -Force
        }
    }
    python scripts\secret_scan.py
    if ($LASTEXITCODE -ne 0) { throw "Secret scan failed; refusing to publish." }
    if (-not $Publish) {
        Write-Output "PREPARED: review the diff; use -Publish explicitly to commit and push these files."
        $copies | ForEach-Object { Write-Output $_.Relative }
        return
    }
    $paths = @($copies | ForEach-Object { $_.Relative })
    git add -- $paths
    if ($LASTEXITCODE -ne 0) { throw "Git staging failed." }
    python scripts\secret_scan.py --staged
    if ($LASTEXITCODE -ne 0) { throw "Staged secret scan failed; refusing to publish." }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Output "No changes to publish."
        return
    }
    if ($LASTEXITCODE -ne 1) { throw "Cannot inspect staged diff." }

    git commit -m $Message
    if ($LASTEXITCODE -ne 0) { throw "Git commit failed; nothing was pushed." }
    git push
    if ($LASTEXITCODE -ne 0) { throw "Git push failed; the local commit is retained." }
    Write-Output "Pushed: $Message"
} finally {
    Pop-Location
}
