#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Required public proof files =="
required_files=(
  "README.md"
  "MPlusForm.toc"
  "MPlusForm.lua"
  "Data/Snapshot.lua"
  "docs/TRUST_MODEL.md"
  "docs/INSTALL_SYNC.md"
  "docs/TROUBLESHOOTING.md"
  "sync/mplusform_sync_service.py"
  "server_patch/mplusform_trust_layer.py"
  "windows/README.md"
)

for path in "${required_files[@]}"; do
  test -f "$path"
  echo "ok $path"
done

echo "== Python syntax =="
python3 -m py_compile \
  sync/mplusform_sync_service.py \
  server_patch/mplusform_trust_layer.py \
  tools/trust_probe_rc10_6.py \
  legacy/server_work_rc10_6/main.py \
  legacy/server_work_rc10_6/mplusform_trust_layer.py

echo "== Lua syntax =="
lua_compiler=""
if command -v luac >/dev/null 2>&1; then
  lua_compiler="luac"
elif command -v luac5.4 >/dev/null 2>&1; then
  lua_compiler="luac5.4"
fi

if [[ -n "$lua_compiler" ]]; then
  "$lua_compiler" -p MPlusForm.lua Data/Snapshot.lua
  echo "ok lua parse via $lua_compiler"
else
  echo "skip lua parse: luac not installed"
fi

echo "== Public package contract =="
python3 - <<'PY'
from pathlib import Path

toc = Path("MPlusForm.toc").read_text(encoding="utf-8")
addon = Path("MPlusForm.lua").read_text(encoding="utf-8")
snapshot = Path("Data/Snapshot.lua").read_text(encoding="utf-8")
trust_model = Path("docs/TRUST_MODEL.md").read_text(encoding="utf-8")

checks = {
    "toc loads snapshot before addon": toc.index("Data\\Snapshot.lua") < toc.index("MPlusForm.lua"),
    "snapshot is server-approved shaped": "serverApproved" in snapshot,
    "addon exposes public truth boundary": "server-approved-snapshot-only" in addon,
    "trust model documents local evidence boundary": "local evidence" in trust_model.lower(),
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("failed public package contract: " + ", ".join(failed))

for name in checks:
    print(f"ok {name}")
PY

echo "public verification passed"
