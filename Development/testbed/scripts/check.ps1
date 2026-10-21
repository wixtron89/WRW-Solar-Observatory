# Windows version of check.sh - compare what reached InfluxDB at SOM and CAM
#   .\scripts\check.ps1          last 15 minutes
#   .\scripts\check.ps1 1h
param([string]$Window = "15m")
Set-Location (Join-Path $PSScriptRoot "..")
$db = (Select-String -Path .env -Pattern '^INFLUX_DB=(.*)$').Matches.Groups[1].Value.Trim()
if (-not $db) { $db = "wrwo" }

foreach ($side in "som", "cam") {
    Write-Host "================ $side"
    docker compose exec -T "influx-$side" influx -database $db -precision rfc3339 -execute `
        "SELECT count(delay_s) AS points, max(delay_s) AS max_delay_s FROM cloudwatcher, seeing WHERE time > now() - $Window"
}
Write-Host ""
Write-Host "== CAM per minute (a 0 = gap)"
docker compose exec -T influx-cam influx -database $db -precision rfc3339 -execute `
    "SELECT count(delay_s), max(delay_s) FROM seeing WHERE time > now() - $Window GROUP BY time(1m) fill(0)"
