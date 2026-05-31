#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/mplusform}"
SERVICE="${SERVICE:-mplusform-api.service}"
PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"

echo "[MPlusForm] Installing rc10.7 server trust layer into $APP_DIR"
mkdir -p "$APP_DIR"
if [ -f "$APP_DIR/mplusform_trust_layer.py" ]; then
  cp "$APP_DIR/mplusform_trust_layer.py" "$APP_DIR/mplusform_trust_layer.py.bak-$TS"
fi
cp "$PATCH_DIR/mplusform_trust_layer.py" "$APP_DIR/mplusform_trust_layer.py"

python3 -m py_compile "$APP_DIR/mplusform_trust_layer.py"

echo "[MPlusForm] Trust layer copied and syntax-checked."

ENV_FILE="${ENV_FILE:-/etc/mplusform.env}"
DROPIN_DIR="/etc/systemd/system/${SERVICE}.d"
mkdir -p "$DROPIN_DIR"
if [ ! -f "$ENV_FILE" ]; then
  if command -v openssl >/dev/null 2>&1; then
    SECRET="$(openssl rand -hex 32)"
  else
    SECRET="$(python3 - <<'PY2'
import secrets
print(secrets.token_hex(32))
PY2
)"
  fi
  cat > "$ENV_FILE" <<EOF
MPLUSFORM_DB_PATH=$APP_DIR/data/mplusform.sqlite3
MPLUSFORM_SNAPSHOT_SECRET=$SECRET
MPLUSFORM_MIN_HEARTBEATS_FOR_APPROVAL=1
MPLUSFORM_MAX_DAMAGE_DRIFT_RATIO=0.02
EOF
  chmod 600 "$ENV_FILE"
  echo "[MPlusForm] Created $ENV_FILE with generated snapshot secret."
else
  echo "[MPlusForm] Using existing $ENV_FILE"
fi
cat > "$DROPIN_DIR/mplusform-trust.conf" <<EOF
[Service]
EnvironmentFile=$ENV_FILE
EOF
systemctl daemon-reload

echo "[MPlusForm] Manual integration still required if your app does not import the router yet:"
echo "    from mplusform_trust_layer import router as mplusform_trust_router"
echo "    app.include_router(mplusform_trust_router)"
echo
read -r -p "Restart $SERVICE now? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
  systemctl restart "$SERVICE"
  systemctl --no-pager --full status "$SERVICE" || true
fi
