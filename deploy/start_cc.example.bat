@echo off
setlocal

rem Edit BOT_ROOT to your work directory.
set "BOT_ROOT=C:\ai-companion"
set "CC_DIR=%USERPROFILE%\.cc-connect"
set "CC_LOG_DIR=%CC_DIR%\logs"
if not exist "%CC_LOG_DIR%" mkdir "%CC_LOG_DIR%"
echo [%date% %time%] launcher started >> "%CC_DIR%\launcher.log"

rem Avoid duplicate instances.
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command "if (Get-Process -Name cc-connect -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }" 2^>nul`) do set "CC_RUNNING=%%R"
if /I "%CC_RUNNING%"=="yes" (
  echo [%date% %time%] already running >> "%CC_DIR%\launcher.log"
  exit /b 0
)

rem Optional: point at the Codex CLI bundled with the Windows MSIX app.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "(Get-AppxPackage -Name 'OpenAI.Codex' -ErrorAction SilentlyContinue).InstallLocation" 2^>nul`) do set "CODEX_APP=%%P"
if defined CODEX_APP if exist "%CODEX_APP%\app\resources\codex.exe" (
  set "CC_CODEX_REAL=%CODEX_APP%\app\resources\codex.exe"
  set "PATH=%BOT_ROOT%\bin;%PATH%"
)

set "CC_LOG=%CC_LOG_DIR%\cc-connect-%RANDOM%%RANDOM%.log"
echo [%date% %time%] starting cc-connect >> "%CC_LOG%"

rem Prefer the global npm install. Adjust if yours lives elsewhere.
"%APPDATA%\npm\node_modules\cc-connect\bin\cc-connect.exe" --config "%CC_DIR%\config.toml" --force >> "%CC_LOG%" 2>&1
