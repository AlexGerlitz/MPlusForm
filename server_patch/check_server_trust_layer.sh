#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8015}"
echo "== health =="
curl -fsS "$BASE/api/v1/health/trust"; echo
echo "== stats =="
curl -fsS "$BASE/api/v1/stats"; echo
echo "== snapshot =="
curl -fsS "$BASE/api/v1/snapshot.json" | python3 -m json.tool | head -80
