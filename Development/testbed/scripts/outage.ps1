# Windows (Docker Desktop) version of outage.sh
#   .\scripts\outage.ps1 cam 60
#   .\scripts\outage.ps1 bridge
param([string]$What = "cam", [int]$Duration = 60)
Set-Location (Join-Path $PSScriptRoot "..")
if ($What -eq "bridge") { docker compose restart mqbridge; exit }
$svc = "mqbroker-$What"
Write-Host ">>> $svc DOWN for $Duration s at $(Get-Date -Format HH:mm:ss)"
docker compose stop $svc
Start-Sleep -Seconds $Duration
docker compose start $svc
Write-Host ">>> $svc UP. Check: docker compose logs mqbridge"
