# Start the dev tunnel, read its public URL, write it to WEBHOOK_URL in .env and recreate n8n
# so Telegram triggers re-register their webhook with the new URL.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

docker compose --profile dev up -d --force-recreate webhook-gw tunnel | Out-Null

$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep -Seconds 2
    $m = docker compose logs tunnel 2>&1 | Select-String -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1
    if ($m) { $url = $m.Matches[0].Value }
}
if (-not $url) { throw "Could not find tunnel URL in logs" }

$envPath = Resolve-Path ".env"
$content = [IO.File]::ReadAllText($envPath)
$content = $content -replace '(?m)^WEBHOOK_URL=.*$', "WEBHOOK_URL=$url/"
[IO.File]::WriteAllText($envPath, $content)

docker compose up -d n8n | Out-Null

# n8n keeps already-registered trigger webhooks across restarts, so cycle the Telegram
# workflow to make it call setWebhook with the new URL.
$wf = "wf01telegramentry"
Start-Sleep -Seconds 15
docker compose exec -T n8n n8n unpublish:workflow --id=$wf | Out-Null
docker compose restart n8n | Out-Null
Start-Sleep -Seconds 15
docker compose exec -T n8n n8n publish:workflow --id=$wf | Out-Null
docker compose restart n8n | Out-Null
Write-Host "WEBHOOK_URL=$url/"
