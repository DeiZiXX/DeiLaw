#!/bin/sh
set -eu
# An initial failed update keeps /health unhealthy and every scan blocked.
freshclam --stdout || true
(
  while sleep 3600; do
    freshclam --stdout >/dev/null 2>&1 || true
  done
) &
exec python3 /opt/deilaw-av/clamav_gateway.py
