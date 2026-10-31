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
    "common.py", "send_msg.py", "send_xi.py", "add_reminder.py",
    "care_scheduler.py", "capture_transcripts.py", "healthcheck.py",
    "backup.ps1", "setup_tasks.ps1"
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
