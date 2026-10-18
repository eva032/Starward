#!/usr/bin/env bash
# Start Flask (port 5001) and the Photon bridge together. Ctrl+C stops both.
# Does not modify .env files or application code. Uses existing venv / npm setup.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/venv/bin/python" ]]; then
  PYTHON="$ROOT/venv/bin/python"
else
  PYTHON="python3"
fi

if [[ ! -d "$ROOT/bridge/node_modules" ]]; then
  echo "[start] bridge/node_modules missing. Run: cd bridge && npm install" >&2
  exit 1
fi

if [[ ! -f "$ROOT/bridge/.env" ]]; then
  echo "[start] bridge/.env missing. Copy bridge/.env.example and add Spectrum credentials." >&2
  exit 1
fi

# Job control so background services get their own process groups (clean Ctrl+C).
set -m

FLASK_PID=""
BRIDGE_PID=""
STOPPING=0

shutdown() {
  if [[ "$STOPPING" -eq 1 ]]; then
    return
  fi
  STOPPING=1
  trap - INT TERM EXIT
  echo ""
  echo "[start] Shutting down Flask and Photon bridge..."

  for pid in $FLASK_PID $BRIDGE_PID; do
    [[ -n "$pid" ]] || continue
    if kill -0 "$pid" 2>/dev/null; then
      # Negative PID = process group (reloader / npm children included).
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  # Brief grace period, then force-kill any stragglers in those groups.
  sleep 0.5
  for pid in $FLASK_PID $BRIDGE_PID; do
    [[ -n "$pid" ]] || continue
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
    # Flask debug reloader / npm may leave orphans still parented under the old PID.
    pkill -TERM -P "$pid" 2>/dev/null || true
  done

  wait 2>/dev/null || true
  echo "[start] Stopped."
  exit 0
}

trap shutdown INT TERM

echo "[start] Flask → http://127.0.0.1:5001"
# PORT only for this process (do not export — bridge uses its own PORT / 8787).
PORT=5001 "$PYTHON" app.py &
FLASK_PID=$!

echo "[start] Photon bridge → npm run start (http://127.0.0.1:8787)"
(
  cd "$ROOT/bridge" || exit 1
  # Point inbound webhooks at Flask on 5001 without editing bridge/.env on disk.
  # Node/tsx --env-file does not override variables already in the environment.
  export FLASK_WEBHOOK_URL="${FLASK_WEBHOOK_URL:-http://127.0.0.1:5001/webhook/photon}"
  npm run start
) &
BRIDGE_PID=$!

echo "[start] Both running. Logs are interleaved below. Press Ctrl+C to stop."
echo ""

# If either service exits, tear down the other.
while true; do
  flask_alive=0
  bridge_alive=0
  kill -0 "$FLASK_PID" 2>/dev/null && flask_alive=1
  kill -0 "$BRIDGE_PID" 2>/dev/null && bridge_alive=1

  if [[ "$flask_alive" -eq 0 || "$bridge_alive" -eq 0 ]]; then
    if [[ "$STOPPING" -eq 0 ]]; then
      echo "[start] A service exited; shutting down the rest." >&2
      shutdown
    fi
    break
  fi
  sleep 1
done
