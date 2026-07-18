# Start an outbound-only Cloudflare quick tunnel for the CRT terminal
# and write the public URL into .env (BBS_WEB_URL). Then restart the bot.
#
# Usage:  powershell -ExecutionPolicy Bypass -File tunnel.ps1
# The tunnel keeps running in the background until you kill cloudflared
# or reboot. Quick-tunnel URLs change on every start -- rerun this
# script (and restart the bot) after a reboot.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8737
$envFile = Join-Path $root ".env"
$log = Join-Path $root "data\tunnel.log"

New-Item -ItemType Directory -Force (Join-Path $root "data") | Out-Null
if (Test-Path $log) { Remove-Item $log -Force }

# already running?
$existing = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "cloudflared already running (pid $($existing.Id -join ', ')) -- killing it to get a fresh URL"
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 1
}

Write-Host "starting tunnel -> http://localhost:$port ..."
Start-Process -WindowStyle Hidden -FilePath "cloudflared" `
    -ArgumentList "tunnel", "--url", "http://localhost:$port" `
    -RedirectStandardError $log

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
    exit 1
}

# write BBS_WEB_URL into .env (replace existing line or append)
if (Test-Path $envFile) {
    $content = Get-Content $envFile -Raw -Encoding utf8
    if ($content -match "(?m)^BBS_WEB_URL=") {
        $content = $content -replace "(?m)^BBS_WEB_URL=.*$", "BBS_WEB_URL=$url"
    } else {
        if (-not $content.EndsWith("`n")) { $content += "`r`n" }
        $content += "BBS_WEB_URL=$url`r`n"
    }
    [System.IO.File]::WriteAllText($envFile, $content)
} else {
    [System.IO.File]::WriteAllText($envFile, "BBS_WEB_URL=$url`r`n")
}

Write-Host ""
Write-Host "  tunnel up:  $url"
Write-Host "  written to: $envFile"
Write-Host ""
Write-Host "  now (re)start the bot -- the [W] CRT TERMINAL button will appear."
