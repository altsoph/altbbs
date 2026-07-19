# altBBS launcher: kill previous bot + tunnel, start fresh, wire the URL.
# Usage: .\start.ps1   (or: powershell -ExecutionPolicy Bypass -File start.ps1)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$port = 8737
$envFile = Join-Path $root ".env"
$log = Join-Path $root "data\tunnel.log"
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"

# --- 1. kill previous instances ----------------------------------------
$bots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "run\.py" -and $_.CommandLine -match [regex]::Escape($root) }
foreach ($p in $bots) {
    Write-Host "killing old bbs (pid $($p.ProcessId))"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "killing old tunnel (pid $($_.Id))"
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 1

# --- 2. fresh tunnel log (retry: cloudflared may release the file late) -
New-Item -ItemType Directory -Force (Join-Path $root "data") | Out-Null
foreach ($i in 1..5) {
    try {
        if (Test-Path $log) { Remove-Item $log -Force }
        break
    } catch { Start-Sleep -Seconds 1 }
}

# --- 3. start tunnel, wait for its URL ----------------------------------
Write-Host "starting tunnel -> http://localhost:$port ..."
$tunnel = Start-Process -WindowStyle Hidden -FilePath $cloudflared `
    -ArgumentList "tunnel", "--url", "http://localhost:$port" `
    -RedirectStandardError $log -PassThru

$url = $null
foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
        $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue
        if ($m) { $url = $m.Matches[0].Value; break }
    }
}
if (-not $url) {
    Write-Host "FAILED: no tunnel URL after 30s. See $log"
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    exit 1
}

# --- 4. write BBS_WEB_URL into .env so the [W] button gets the new URL --
$content = Get-Content $envFile -Raw -Encoding utf8
if ($content -match "(?m)^BBS_WEB_URL=") {
    $content = $content -replace "(?m)^BBS_WEB_URL=.*$", "BBS_WEB_URL=$url"
} else {
    if (-not $content.EndsWith("`n")) { $content += "`r`n" }
    $content += "BBS_WEB_URL=$url`r`n"
}
[System.IO.File]::WriteAllText($envFile, $content)

Write-Host ""
Write-Host "  tunnel up: $url" -ForegroundColor Green
Write-Host ""

# --- 5. bot in the foreground; ctrl-c stops it, tunnel dies with it -----
# Start-Process (not `&`) so PS never wraps the bot's stderr log lines into
# errors; PYTHONUTF8 so the box-drawing masthead survives any console codepage.
$env:PYTHONUTF8 = "1"
try {
    $bot = Start-Process -FilePath $python -ArgumentList "run.py" `
        -WorkingDirectory $root -NoNewWindow -Wait -PassThru
    Write-Host "bbs exited (code $($bot.ExitCode))"
} finally {
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    Write-Host "tunnel stopped."
}
