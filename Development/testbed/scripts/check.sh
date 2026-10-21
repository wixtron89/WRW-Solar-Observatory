#!/usr/bin/env bash
# Compare what reached InfluxDB at SOM and at CAM.
#   ./scripts/check.sh          last 15 minutes
#   ./scripts/check.sh 1h
# Uses ROLE from .env: the local side goes through docker compose, the other side over
# the network (ROLE=som -> CAM_IP, ROLE=cam -> SOM_IP if set).
set -euo pipefail
cd "$(dirname "$0")/.."
WIN="${1:-15m}"
envget() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '\r' | sed 's/[[:space:]]#.*//; s/[[:space:]]*$//' || true; }
ROLE="$(envget ROLE)"; ROLE="${ROLE:-all}"
DB="$(envget INFLUX_DB)"; DB="${DB:-wrwo}"
VER="$(envget INFLUX_VERSION)"; VER="${VER:-1.12}"

# where each side is: "local" or host:port ("" = unreachable from here)
SOM_AT=local; CAM_AT=local
case "$ROLE" in
  som) ip="$(envget CAM_IP)"; p="$(envget CAM_INFLUX_PORT)"; CAM_AT="${ip:+$ip:${p:-8087}}" ;;
  cam) ip="$(envget SOM_IP)"; p="$(envget SOM_INFLUX_PORT)"; SOM_AT="${ip:+$ip:${p:-8086}}" ;;
esac

# influxq <som|cam> <influx CLI args...>
influxq() {
  local side="$1"; shift
  local at; [ "$side" = som ] && at="$SOM_AT" || at="$CAM_AT"
  if [ "$at" = local ]; then
    docker compose exec -T "influx-$side" influx "$@"
  elif [ -n "$at" ]; then
    docker run --rm --network host "influxdb:$VER" influx -host "${at%:*}" -port "${at##*:}" "$@"
  else
    echo "(skipped: set $( [ "$side" = som ] && echo SOM_IP || echo CAM_IP ) in .env)"
  fi
}

for side in som cam; do
  echo "================ $side"
  influxq "$side" -database "$DB" -precision rfc3339 -execute \
    "SELECT count(delay_s) AS points, max(delay_s) AS max_delay_s FROM cloudwatcher, seeing WHERE time > now() - $WIN" || true
done
echo
echo "== CAM per minute (a 0 = gap; after a CAM outage there should be none, only larger delay)"
influxq cam -database "$DB" -precision rfc3339 -execute \
  "SELECT count(delay_s), max(delay_s) FROM seeing WHERE time > now() - $WIN GROUP BY time(1m) fill(0)" || true
