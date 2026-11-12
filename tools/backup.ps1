param(
    [string]$BotRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CcDataDir = (Join-Path $env:USERPROFILE ".cc-connect"),
    [string]$DestinationRoot = "",
    [switch]$Full,
    [switch]$NoPrune,
    [int]$DailyKeepDays = 14,
    [int]$FullKeepDays = 28,
    [int]$LegacyKeepDays = 7
)

$ErrorActionPreference = "Stop"

if (-not $DestinationRoot) {
    if (Test-Path "G:\") {
        $DestinationRoot = "G:\cc-weixin-backups"
    } else {
        $DestinationRoot = Join-Path $BotRoot "backups"
    }
}
New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null

$isFull = $Full.IsPresent -or ((Get-Date).DayOfWeek -eq "Sunday")
$mode = if ($isFull) { "full" } else { "daily" }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stage = Join-Path $DestinationRoot ("stage-" + $stamp)
$botDir = Join-Path $stage "bot"
$ccDir = Join-Path $stage "cc-connect"
$codexDir = Join-Path $stage "codex"
New-Item -ItemType Directory -Force -Path $botDir, $ccDir, $codexDir | Out-Null

function Copy-Safe([string]$src, [string]$dst) {
    if (Test-Path -LiteralPath $src) {
        try {
            Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Warning ("copy failed: " + $src + " -> " + $_.Exception.Message)
        }
    }
}

# Always small: identity, memory, tools, config, docs and wrappers.
foreach ($name in @("PERSONA.md", "AGENTS.md", "README.md", "MAINTENANCE-TIMERS.md")) {
    Copy-Safe (Join-Path $BotRoot $name) $botDir
}
$binDir = Join-Path $botDir "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
Copy-Safe (Join-Path $BotRoot "memory") $botDir
Copy-Safe (Join-Path $BotRoot "tools") $botDir
Copy-Safe (Join-Path $BotRoot "config") $botDir
Copy-Safe (Join-Path $BotRoot "bin\codex.exe") $binDir

if ($isFull) {
    # Weekly full: include the sticker images, cc-connect binaries and release notes.
    Copy-Safe (Join-Path $BotRoot "assets") $botDir
    Copy-Safe (Join-Path $BotRoot "maintenance") $botDir
    Copy-Safe (Join-Path $BotRoot "bin\cc-connect.exe") $binDir
    Copy-Safe (Join-Path $BotRoot "bin\cc-connect-patched.exe") $binDir
} else {
    # Daily light: keep sticker metadata only; images live in the weekly full.
    $assetDir = Join-Path $botDir "assets\stickers"
    New-Item -ItemType Directory -Force -Path $assetDir | Out-Null
    foreach ($name in @("manifest.json", "sticker_tags.json", "feedback.json", "CATEGORIES.md", "SOURCES.md")) {
        Copy-Safe (Join-Path $BotRoot ("assets\stickers\" + $name)) $assetDir
    }
    $maintDir = Join-Path $botDir "maintenance"
    New-Item -ItemType Directory -Force -Path $maintDir | Out-Null
    foreach ($name in @("active-memory-release.json", "active-timer-release.json")) {
        Copy-Safe (Join-Path $BotRoot ("maintenance\" + $name)) $maintDir
    }
}

# Isolated Codex config (auth.json intentionally excluded).
Copy-Safe (Join-Path $BotRoot ".codex\config.toml") $codexDir

# cc-connect config, schedules, sessions, launchers.
Copy-Safe (Join-Path $CcDataDir "config.toml") $ccDir
Copy-Safe (Join-Path $CcDataDir "crons") $ccDir
Copy-Safe (Join-Path $CcDataDir "sessions") $ccDir
Copy-Safe (Join-Path $CcDataDir "start_cc.bat") $ccDir
Copy-Safe (Join-Path $CcDataDir "start_cc_hidden.vbs") $ccDir

# Version / restore notes.
$versions = @()
$versions += "Backup mode: " + $mode
$versions += "Bot root: " + $BotRoot
$cc = Join-Path $env:APPDATA "npm\node_modules\cc-connect\bin\cc-connect.exe"
if (Test-Path -LiteralPath $cc) {
    $versions += (& $cc --version 2>&1 | Out-String).Trim()
}
$pkg = Get-AppxPackage -Name "OpenAI.Codex" -ErrorAction SilentlyContinue
if ($pkg) {
    $versions += "Codex MSIX: " + $pkg.Version
}
$versions += "Backup time: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
$versions | Set-Content -Path (Join-Path $stage "VERSIONS.txt") -Encoding UTF8

# Startup shortcut.
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "cc-connect-weixin.lnk"
if (Test-Path -LiteralPath $lnk) {
    Copy-Item -LiteralPath $lnk -Destination (Join-Path $stage "cc-connect-weixin.lnk") -Force
}

$zip = Join-Path $DestinationRoot ("cc-weixin-" + $mode + "-" + $stamp + ".zip")
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item -LiteralPath $stage -Recurse -Force

function Prune-Pattern([string]$pattern, [int]$days, [switch]$KeepNewest) {
    if ($NoPrune -or $days -le 0) { return }
    $cutoff = (Get-Date).AddDays(-$days)
    $items = @(Get-ChildItem -Path $DestinationRoot -Filter $pattern -File -ErrorAction SilentlyContinue |
               Sort-Object LastWriteTime -Descending)
    if ($KeepNewest -and $items.Count -gt 0) {
        $items = @($items | Select-Object -Skip 1)
    }
    foreach ($item in $items) {
        if ($item.LastWriteTime -lt $cutoff) {
            Remove-Item -LiteralPath $item.FullName -Force
            Write-Output ("PRUNE " + $item.Name)
        }
    }
}

Prune-Pattern "cc-weixin-daily-*.zip" $DailyKeepDays
Prune-Pattern "cc-weixin-full-*.zip" $FullKeepDays
Prune-Pattern "cc-weixin-backup-*.zip" $LegacyKeepDays -KeepNewest

# Rotate launch logs older than 14 days; trim the launcher log.
$logDir = Join-Path $CcDataDir "logs"
if (Test-Path -LiteralPath $logDir) {
    Get-ChildItem -Path $logDir -Filter "*.log" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
$launcher = Join-Path $CcDataDir "launcher.log"
if (Test-Path -LiteralPath $launcher) {
    $tail = Get-Content -LiteralPath $launcher -Tail 500 -ErrorAction SilentlyContinue
    if ($tail) { $tail | Set-Content -LiteralPath $launcher -Encoding UTF8 }
}

$log = Join-Path $DestinationRoot "backup.log"
Add-Content -Path $log -Value ((Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " BACKUP_OK " + $zip + " mode=" + $mode)
Write-Output ("BACKUP_OK " + $zip + " mode=" + $mode)