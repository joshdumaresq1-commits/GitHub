#!/usr/bin/env bash
# Evening finance refresh script
# Run this each evening to sync Gmail and open the review queue

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_BASE="http://localhost:8000"

echo "==================================="
echo "  Finance Tracker - Evening Refresh"
echo "==================================="
echo ""

# Check if server is running
if ! curl -sf "$API_BASE/" > /dev/null 2>&1; then
  echo "[WARN] Finance Tracker server is not running."
  echo "       Start it with:  cd $SCRIPT_DIR && uvicorn backend.main:app"
  echo ""
  read -rp "Start the server now? [y/N] " start_now
  if [[ "${start_now,,}" == "y" ]]; then
    echo "[INFO] Starting server in background…"
    cd "$SCRIPT_DIR"
    nohup uvicorn backend.main:app --host 0.0.0.0 --port 8000 > data/server.log 2>&1 &
    echo "[INFO] Waiting for server to start…"
    for i in {1..15}; do
      sleep 1
      if curl -sf "$API_BASE/" > /dev/null 2>&1; then
        echo "[OK] Server is up."
        break
      fi
    done
  else
    echo "[EXIT] Please start the server and re-run this script."
    exit 1
  fi
else
  echo "[OK] Server is running at $API_BASE"
fi

echo ""
echo "[INFO] Syncing Gmail…"

# Read label from config (default: Finance)
LABEL="Finance"
CONFIG_FILE="$SCRIPT_DIR/data/config.json"
if [[ -f "$CONFIG_FILE" ]]; then
  LABEL=$(python3 -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('gmail_label','Finance'))" 2>/dev/null || echo "Finance")
fi

SYNC_RESULT=$(curl -sf -X POST "$API_BASE/api/gmail/sync?label=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$LABEL'))")" 2>/dev/null || echo '{"message":"Gmail sync skipped (credentials not set up)","imported":0}')
IMPORTED=$(echo "$SYNC_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('imported',0))" 2>/dev/null || echo "0")
MSG=$(echo "$SYNC_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null || echo "")

echo "[INFO] $MSG"
echo ""

# Get review queue count
QUEUE_COUNT=$(curl -sf "$API_BASE/api/review-queue" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "?")
echo "[INFO] Transactions pending review: $QUEUE_COUNT"
echo ""

if [[ "$QUEUE_COUNT" == "0" ]]; then
  echo "✓ Nothing to review tonight. All caught up!"
  echo ""
  echo "Dashboard: $API_BASE/"
  exit 0
fi

echo "[INFO] Opening review queue in browser…"
REVIEW_URL="$API_BASE/review.html"

# Detect OS and open browser
if command -v xdg-open &> /dev/null; then
  xdg-open "$REVIEW_URL"
elif command -v open &> /dev/null; then
  open "$REVIEW_URL"
elif command -v start &> /dev/null; then
  start "$REVIEW_URL"
else
  echo "[WARN] Could not auto-open browser. Navigate to: $REVIEW_URL"
fi

echo ""
echo "Review queue: $REVIEW_URL"
echo "==================================="
