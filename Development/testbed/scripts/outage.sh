#!/usr/bin/env bash
# Simulate failures.
#   ./scripts/outage.sh cam 60       CAM broker down 60 s  (= SOM->CAM link down)
#   ./scripts/outage.sh som 30       SOM broker down 30 s
#   ./scripts/outage.sh bridge       restart MQ-BRIDGE (queue must survive)
#   ./scripts/outage.sh link 120     SOM machine (ROLE=som, Linux, sudo): silently DROP
#                                    bridge traffic to CAM_IP:CAM_BROKER_PUBLISH_PORT, like
#                                    a WiFi/cable loss; SSH and everything else stay up
set -euo pipefail
cd "$(dirname "$0")/.."
WHAT="${1:-cam}"; DUR="${2:-60}"
envget() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '\r' | sed 's/[[:space:]]#.*//; s/[[:space:]]*$//' || true; }

case "$WHAT" in
  cam|som)
    svc="mqbroker-$WHAT"
    echo ">>> $svc DOWN for ${DUR}s at $(date +%T)"
    docker compose stop "$svc"
    sleep "$DUR"
    docker compose start "$svc"
    echo ">>> $svc UP at $(date +%T)  - check: ./scripts/check.sh" ;;
  bridge)
    echo ">>> restarting mqbridge at $(date +%T)"
    docker compose restart mqbridge ;;
  link)
    [ "$(envget ROLE)" = som ] || { echo "link: run this on the SOM machine (ROLE=som)"; exit 1; }
    host="$(envget CAM_IP)"; port="$(envget CAM_BROKER_PUBLISH_PORT)"; port="${port:-1885}"
    [ -n "$host" ] || { echo "set CAM_IP in .env first"; exit 1; }
    # container traffic passes FORWARD, so the rule goes into Docker's DOCKER-USER chain
    rule=(DOCKER-USER -d "$host" -p tcp --dport "$port" -j DROP)
    trap 'sudo iptables -D "${rule[@]}" 2>/dev/null || true' EXIT
    echo ">>> link SOM->CAM ($host:$port) DROPPED for ${DUR}s at $(date +%T)"
    sudo iptables -I "${rule[@]}"
    sleep "$DUR"
    sudo iptables -D "${rule[@]}"
    trap - EXIT
    echo ">>> link UP at $(date +%T)  - check: ./scripts/check.sh" ;;
  *) echo "usage: $0 cam|som|bridge|link [seconds]"; exit 1 ;;
esac
