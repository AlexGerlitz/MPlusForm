from __future__ import annotations

import json
import sqlite3
import time
import urllib.request


BASE = "http://127.0.0.1:8015"
DB = "/opt/mplusform/data/mplusform.sqlite"
stamp = int(time.time())
run_id = f"codex-trust-probe-{stamp}"
session_id = f"{run_id}-session"
uploader_id = "codex-trust-probe"
started_at = stamp - 900
completed_at = stamp


def post(path: str, payload: dict) -> dict:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-MPlusForm-Uploader": uploader_id,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


players = [
    {"name": "CodexProbeA", "realm": "CodexProbe", "totalDamage": 90_000_000, "deaths": 0, "interrupts": 3},
    {"name": "CodexProbeB", "realm": "CodexProbe", "totalDamage": 30_000_000, "deaths": 1, "interrupts": 1},
    {"name": "CodexProbeC", "realm": "CodexProbe", "totalDamage": 45_000_000, "deaths": 0, "interrupts": 7},
    {"name": "CodexProbeD", "realm": "CodexProbe", "totalDamage": 85_000_000, "deaths": 0, "interrupts": 12},
    {"name": "CodexProbeE", "realm": "CodexProbe", "totalDamage": 80_000_000, "deaths": 0, "interrupts": 4},
]
total_damage = sum(p["totalDamage"] for p in players)
deaths = sum(p["deaths"] for p in players)
interrupts = sum(p["interrupts"] for p in players)

heartbeat = {
    "schemaVersion": "mplusform_live_evidence_v1",
    "uploader": {"id": uploader_id, "client": "codex-probe"},
    "heartbeat": {
        "sessionId": session_id,
        "evidenceRunId": run_id,
        "status": "completed",
        "completed": True,
        "abandoned": False,
        "startedAt": started_at,
        "completedAt": completed_at,
        "totalDamage": total_damage,
        "deaths": deaths,
        "interrupts": interrupts,
        "tamperEvidence": {
            "heartbeatSeq": 1,
            "prevHeartbeatChainHash": "",
            "heartbeatChainHash": "a" * 64,
            "combatLogChainHash": "b" * 64,
        },
    },
}

final_run = {
    "schemaVersion": "mplusform_run_v1",
    "uploader": {"id": uploader_id, "client": "codex-probe"},
    "run": {
        "runId": run_id,
        "evidenceRunId": run_id,
        "region": "EU",
        "realm": "CodexProbe",
        "dungeon": "Codex Test Dungeon",
        "dungeonId": 999001,
        "keyLevel": 2,
        "startedAt": started_at,
        "completedAt": completed_at,
        "durationSec": 900,
        "totalDamage": total_damage,
        "deaths": deaths,
        "interrupts": interrupts,
        "players": players,
    },
}

print("RUN_ID", run_id)
print("HEARTBEAT", json.dumps(post("/api/v1/live-evidence/heartbeat", heartbeat), ensure_ascii=False, sort_keys=True))
print("FINAL_RUN", json.dumps(post("/api/v1/runs", final_run), ensure_ascii=False, sort_keys=True))
print("STATS_BEFORE_CLEANUP", json.dumps(get("/api/v1/stats"), ensure_ascii=False, sort_keys=True))

conn = sqlite3.connect(DB)
try:
    cur = conn.cursor()
    cur.execute("DELETE FROM live_evidence_heartbeats WHERE evidence_run_id=?", (run_id,))
    cur.execute("DELETE FROM raw_run_uploads WHERE evidence_run_id=?", (run_id,))
    cur.execute("DELETE FROM approved_runs WHERE evidence_run_id=?", (run_id,))
    cur.execute("DELETE FROM trust_events WHERE evidence_run_id=?", (run_id,))
    conn.commit()
finally:
    conn.close()

print("STATS_AFTER_CLEANUP", json.dumps(get("/api/v1/stats"), ensure_ascii=False, sort_keys=True))
