"""Example FastAPI server-side patch for MPlusForm rc10.6 live evidence.
This is intentionally append-only and separate from public approved snapshots.
Adapt table/DB code to the real VPS app before production.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
DB_PATH = Path("/opt/mplusform/data/mplusform.sqlite3")


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canon(payload).encode("utf-8")).hexdigest()


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS live_evidence_heartbeats (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      received_at INTEGER NOT NULL,
      uploader_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      evidence_run_id TEXT NOT NULL,
      status TEXT NOT NULL,
      heartbeat_seq INTEGER,
      combatlog_chain_hash TEXT,
      heartbeat_chain_hash TEXT,
      prev_heartbeat_chain_hash TEXT,
      payload_hash TEXT NOT NULL,
      payload_json TEXT NOT NULL
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_live_evidence_session ON live_evidence_heartbeats(session_id, heartbeat_seq)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_live_evidence_run ON live_evidence_heartbeats(evidence_run_id)")
    return conn


@router.post("/api/v1/live-evidence/heartbeat")
async def live_evidence_heartbeat(request: Request):
    payload = await request.json()
    if payload.get("schemaVersion") != "mplusform_live_evidence_v1":
        raise HTTPException(status_code=400, detail="bad schemaVersion")
    uploader = payload.get("uploader") or {}
    hb = payload.get("heartbeat") or {}
    te = hb.get("tamperEvidence") or {}
    session_id = str(hb.get("sessionId") or "")
    if not session_id:
        raise HTTPException(status_code=400, detail="missing sessionId")
    uploader_id = str(uploader.get("id") or request.headers.get("X-MPlusForm-Uploader") or "unknown")
    row = (
        int(time.time()),
        uploader_id,
        session_id,
        str(hb.get("evidenceRunId") or ""),
        str(hb.get("status") or "unknown"),
        int(te.get("heartbeatSeq") or 0),
        str(te.get("combatLogChainHash") or ""),
        str(te.get("heartbeatChainHash") or ""),
        str(te.get("prevHeartbeatChainHash") or ""),
        payload_hash(payload),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    with db() as conn:
        # Minimal continuity check: if previous heartbeat exists, current prevHeartbeatChainHash should match it.
        prev = conn.execute(
            "SELECT heartbeat_chain_hash FROM live_evidence_heartbeats WHERE session_id=? ORDER BY heartbeat_seq DESC, id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        continuity = "first"
        if prev:
            continuity = "ok" if str(prev[0] or "") == row[8] else "mismatch"
        conn.execute(
            """INSERT INTO live_evidence_heartbeats
            (received_at,uploader_id,session_id,evidence_run_id,status,heartbeat_seq,combatlog_chain_hash,heartbeat_chain_hash,prev_heartbeat_chain_hash,payload_hash,payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
    return {"ok": True, "sessionId": session_id, "continuity": continuity}


def latest_live_evidence_for_run(evidence_run_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT payload_json FROM live_evidence_heartbeats WHERE evidence_run_id=? ORDER BY heartbeat_seq DESC, id DESC LIMIT 1",
            (evidence_run_id,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row[0])
