#!/usr/bin/env bash
set -euo pipefail

# Runner script to start the lichess bot for a shift, trigger standby, then shut down.
# Behavior:
# - Default shift length: 180 minutes (3 hours)
# - Sends SIGUSR1 as a "standby" notification 5 minutes before the end of the shift
# - After 5 minutes, sends SIGTERM to request graceful shutdown, then SIGKILL if needed

SHIFT_MINUTES=${SHIFT_MINUTES:-180}
STANDBY_MINUTES=${STANDBY_MINUTES:-5}

STANDBY_SECONDS=$(( (SHIFT_MINUTES - STANDBY_MINUTES) * 60 ))
FINAL_WAIT_SECONDS=$(( STANDBY_MINUTES * 60 ))

echo "Starting lichess bot for ${SHIFT_MINUTES} minutes (standby at -${STANDBY_MINUTES} minutes)..."

# Prefer environment variable; if not present, try to read local config (example provided)
if [ -z "${LICHESS_API_TOKEN-}" ]; then
  if [ -f "config/lichess_api.yml" ]; then
    # crude extraction of token from YAML (expects the example structure)
    LICHESS_API_TOKEN=$(grep -E "api_token:" config/lichess_api.yml | sed -E "s/.*api_token:\s*\"?(.*)\"?/\1/")
    export LICHESS_API_TOKEN
    echo "Loaded LICHESS_API_TOKEN from config/lichess_api.yml"
  else
    echo "Warning: LICHESS_API_TOKEN not set. The bot may fail to authenticate unless token is provided via env or config/lichess_api.yml." >&2
  fi
fi

# Start the bot in background
python DRFizzle-BOT-Lichess/lichess_bot.py &
BOT_PID=$!

echo "Bot started with PID $BOT_PID"

sleep ${STANDBY_SECONDS}

if kill -0 "${BOT_PID}" 2>/dev/null; then
  echo "Triggering standby signal (SIGUSR1) to bot PID ${BOT_PID}"
  kill -USR1 "${BOT_PID}" || true
else
  echo "Bot process ${BOT_PID} exited before standby time." >&2
  exit 0
fi

echo "Standby signal sent. Waiting ${FINAL_WAIT_SECONDS} seconds before shutdown..."
sleep ${FINAL_WAIT_SECONDS}

if kill -0 "${BOT_PID}" 2>/dev/null; then
  echo "Sending SIGTERM to bot PID ${BOT_PID} for graceful shutdown"
  kill -TERM "${BOT_PID}" || true
  # wait up to 30 seconds for process to exit
  for i in {1..30}; do
    if ! kill -0 "${BOT_PID}" 2>/dev/null; then
      echo "Bot exited gracefully."
      exit 0
    fi
    sleep 1
  done
  echo "Bot did not exit; sending SIGKILL"
  kill -KILL "${BOT_PID}" || true
else
  echo "Bot process ${BOT_PID} already exited." >&2
fi

echo "Runner finished."
