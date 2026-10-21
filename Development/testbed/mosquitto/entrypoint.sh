#!/bin/sh
# Shared entrypoint for all Mosquitto containers in this testbed.
#  1. renders /mosquitto/config/mosquitto.conf (template, ${VAR} replaced from env)
#     into /mosquitto/run/mosquitto.conf
#  2. builds the password file from MQ_USERS="user1:pass1 user2:pass2"
set -e
RUN=/mosquitto/run
mkdir -p "$RUN"

tr -d '\r' < /mosquitto/config/mosquitto.conf | awk '{
  while (match($0, /\$\{[A-Za-z0-9_]+\}/)) {
    v = substr($0, RSTART + 2, RLENGTH - 3)
    $0 = substr($0, 1, RSTART - 1) ENVIRON[v] substr($0, RSTART + RLENGTH)
  }
  print
}' > "$RUN/mosquitto.conf"

umask 077
rm -f "$RUN/pwfile"; touch "$RUN/pwfile"
for up in $MQ_USERS; do
  mosquitto_passwd -b "$RUN/pwfile" "${up%%:*}" "${up#*:}"
done
chmod 0600 "$RUN/pwfile"
chown -R mosquitto:mosquitto "$RUN" /mosquitto/data 2>/dev/null || true

exec mosquitto -c "$RUN/mosquitto.conf"
