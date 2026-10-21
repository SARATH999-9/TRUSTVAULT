#!/bin/sh
# Starts a throw-away server (empty database, a bootstrap admin, document approval ON, Google configured with a
# fake client id) and drives the real front-end through the whole journey in jsdom.
set -e
cd "$(dirname "$0")/../.."
TMP=$(mktemp -d)
export DATABASE_URL="sqlite:///$TMP/ui.db" STORAGE_DIR="$TMP/storage" ADMIN_EMAIL=admin@uitest.local \
  ADMIN_PASSWORD='Admin-Password-1234' GOOGLE_CLIENT_ID=ui-test.apps.googleusercontent.com REQUIRE_DOCUMENT_APPROVAL=true \
  REGISTER_PER_HOUR=500 LOGIN_PER_5MIN=5000
python -m uvicorn app.main:app --port 8770 >"$TMP/server.log" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null; rm -rf "$TMP"' EXIT
sleep 4
cd tests/ui
[ -d node_modules ] || npm install --silent
BASE_URL=http://127.0.0.1:8770 node smoke.mjs
