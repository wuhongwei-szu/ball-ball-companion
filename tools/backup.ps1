param(
    [string]$BotRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CcDataDir = (Join-Path $env:USERPROFILE ".cc-connect"),
    [string]$DestinationRoot = "",
    [int]$KeepDays = 30
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

# Identity, memory, tools, private local config
Copy-Safe (Join-Path $BotRoot "PERSONA.md") $botDir
Copy-Safe (Join-Path $BotRoot "AGENTS.md") $botDir
Copy-Safe (Join-Path $BotRoot "memory") $botDir
Copy-Safe (Join-Path $BotRoot "tools") $botDir
Copy-Safe (Join-Path $BotRoot "assets") $botDir
$binDir = Join-Path $botDir "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
Copy-Safe (Join-Path $BotRoot "bin\cc-connect.exe") $binDir
Copy-Safe (Join-Path $BotRoot "bin\cc-connect-patched.exe") $binDir
Copy-Safe (Join-Path $BotRoot "config\bot.config.json") $botDir

# Isolated Codex config (auth.json intentionally excluded)
Copy-Safe (Join-Path $BotRoot ".codex\config.toml") $codexDir

# cc-connect config, schedules, sessions, launchers
Copy-Safe (Join-Path $CcDataDir "config.toml") $ccDir
Copy-Safe (Join-Path $CcDataDir "crons") $ccDir
Copy-Safe (Join-Path $CcDataDir "sessions") $ccDir
Copy-Safe (Join-Path $CcDataDir "start_cc.bat") $ccDir
Copy-Safe (Join-Path $CcDataDir "start_cc_hidden.vbs") $ccDir

# Version / restore notes
$versions = @()
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

# Startup shortcut
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "cc-connect-weixin.lnk"
if (Test-Path -LiteralPath $lnk) {
    Copy-Item -LiteralPath $lnk -Destination (Join-Path $stage "cc-connect-weixin.lnk") -Force
}

$zip = Join-Path $DestinationRoot ("cc-weixin-backup-" + $stamp + ".zip")
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item -LiteralPath $stage -Recurse -Force

# Prune old backups
Get-ChildItem -Path $DestinationRoot -Filter "cc-weixin-backup-*.zip" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    Remove-Item -Force

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
Add-Content -Path $log -Value ((Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " BACKUP_OK " + $zip)
Write-Output ("BACKUP_OK " + $zip)
