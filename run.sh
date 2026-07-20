#!/usr/bin/env bash
# One command to run the whole app: pipeline API (Python) + Next.js front end.
# Usage:  ./run.sh      then open http://localhost:3000
set -e
cd "$(dirname "$0")"

# --- make sure deps are here (only does real work the first time) ---
python3 -m pip install -q flask >/dev/null 2>&1 || true
if [ ! -d web/node_modules ]; then
  echo "→ first run: installing front-end deps…"
  (cd web && npm install)
fi

# --- start the Python pipeline API in the background ---
echo "→ starting pipeline API on http://127.0.0.1:5050"
python3 webapp/app.py &
API_PID=$!

# when this script stops (Ctrl-C or exit), stop the API too
cleanup() { echo; echo "→ shutting down…"; kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# give the API a moment to bind the port
sleep 1

# --- run the Next.js front end in the foreground ---
echo "→ starting front end on http://localhost:3000"
echo
cd web && npm run dev
