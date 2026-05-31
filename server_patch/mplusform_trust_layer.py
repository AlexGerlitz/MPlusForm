"""
MPlusForm server trust layer, rc10.7.

Purpose:
- keep local client files untrusted;
- accept live heartbeat evidence separately from public stats;
- validate final /api/v1/runs against live evidence;
- approve only server-validated completed runs;
- generate signed server-approved snapshots.

Integration:
    from mplusform_trust_layer import router as mplusform_trust_router
    app.include_router(mplusform_trust_router)

If the existing app already defines POST /api/v1/runs, replace that handler with
trusted_runs_endpoint logic or include this router before the old route.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

VERSION = "1.4.2-rc10.7-server-trust-layer"
router = APIRouter()

DB_PATH = Path(os.environ.get("MPLUSFORM_DB_PATH", "/opt/mplusform/data/mplusform.sqlite3"))
SNAPSHOT_SECRET = os.environ.get("MPLUSFORM_SNAPSHOT_SECRET", "dev-change-this-secret-before-public-release")
MAX_FINAL_VS_LIVE_DAMAGE_DRIFT_RATIO = float(os.environ.get("MPLUSFORM_MAX_DAMAGE_DRIFT_RATIO", "0.02"))
MIN_HEARTBEATS_FOR_APPROVAL = int(os.environ.get("MPLUSFORM_MIN_HEARTBEATS_FOR_APPROVAL", "1"))
LIVE_EVIDENCE_RETENTION_SEC = int(os.environ.get("MPLUSFORM_LIVE_EVIDENCE_RETENTION_SEC", str(3 * 24 * 3600)))
RAW_UPLOAD_RETENTION_SEC = int(os.environ.get("MPLUSFORM_RAW_UPLOAD_RETENTION_SEC", str(7 * 24 * 3600)))
TRUST_EVENT_RETENTION_SEC = int(os.environ.get("MPLUSFORM_TRUST_EVENT_RETENTION_SEC", str(14 * 24 * 3600)))
CLEANUP_INTERVAL_SEC = int(os.environ.get("MPLUSFORM_CLEANUP_INTERVAL_SEC", "300"))
LAST_CLEANUP_AT = 0


def now() -> int:
    return int(time.time())


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    return sha256_text(canon(payload))


def sign_payload(payload: dict[str, Any]) -> str:
    raw = canon(payload).encode("utf-8")
    return hmac.new(SNAPSHOT_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def lua_value(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    child = "  " * (indent + 1)
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, list):
        if not value:
            return "{}"
        items = [child + lua_value(item, indent + 1) for item in value]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = []
        for key in sorted(value.keys(), key=lambda x: str(x)):
            items.append(child + "[" + lua_string(str(key)) + "] = " + lua_value(value[key], indent + 1))
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    return lua_string(str(value))


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS live_evidence_heartbeats (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          received_at INTEGER NOT NULL,
          uploader_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          evidence_run_id TEXT NOT NULL,
          status TEXT NOT NULL,
          heartbeat_seq INTEGER NOT NULL,
          combatlog_chain_hash TEXT NOT NULL,
          heartbeat_chain_hash TEXT NOT NULL,
          prev_heartbeat_chain_hash TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          continuity TEXT NOT NULL DEFAULT 'unknown',
          UNIQUE(session_id, heartbeat_seq, payload_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_mpf_live_session ON live_evidence_heartbeats(session_id, heartbeat_seq, id);
        CREATE INDEX IF NOT EXISTS idx_mpf_live_run ON live_evidence_heartbeats(evidence_run_id, heartbeat_seq, id);
        CREATE INDEX IF NOT EXISTS idx_mpf_live_received ON live_evidence_heartbeats(received_at);

        CREATE TABLE IF NOT EXISTS raw_run_uploads (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          received_at INTEGER NOT NULL,
          uploader_id TEXT NOT NULL,
          client_run_id TEXT NOT NULL,
          evidence_run_id TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          verdict TEXT NOT NULL,
          approved INTEGER NOT NULL DEFAULT 0,
          reason TEXT NOT NULL,
          validation_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mpf_raw_run_id ON raw_run_uploads(client_run_id);
        CREATE INDEX IF NOT EXISTS idx_mpf_raw_evidence_id ON raw_run_uploads(evidence_run_id);
        CREATE INDEX IF NOT EXISTS idx_mpf_raw_received ON raw_run_uploads(received_at);

        CREATE TABLE IF NOT EXISTS approved_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          approved_at INTEGER NOT NULL,
          uploader_id TEXT NOT NULL,
          client_run_id TEXT NOT NULL,
          evidence_run_id TEXT NOT NULL,
          dungeon TEXT NOT NULL,
          dungeon_id INTEGER NOT NULL DEFAULT 0,
          key_level INTEGER NOT NULL DEFAULT 0,
          started_at INTEGER NOT NULL,
          completed_at INTEGER NOT NULL,
          duration_sec INTEGER NOT NULL,
          total_damage INTEGER NOT NULL DEFAULT 0,
          deaths INTEGER NOT NULL DEFAULT 0,
          interrupts INTEGER NOT NULL DEFAULT 0,
          avg_group_dps INTEGER NOT NULL DEFAULT 0,
          confidence INTEGER NOT NULL DEFAULT 0,
          trust_status TEXT NOT NULL,
          players_json TEXT NOT NULL,
          source_payload_hash TEXT NOT NULL,
          UNIQUE(client_run_id, source_payload_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_mpf_approved_time ON approved_runs(approved_at);

        CREATE TABLE IF NOT EXISTS trust_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at INTEGER NOT NULL,
          severity TEXT NOT NULL,
          event_type TEXT NOT NULL,
          uploader_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          evidence_run_id TEXT NOT NULL,
          message TEXT NOT NULL,
          details_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mpf_trust_created ON trust_events(created_at);
        """
    )


def maybe_cleanup_old_evidence(conn: sqlite3.Connection) -> None:
    global LAST_CLEANUP_AT
    current = now()
    if current - LAST_CLEANUP_AT < CLEANUP_INTERVAL_SEC:
        return
    LAST_CLEANUP_AT = current
    if LIVE_EVIDENCE_RETENTION_SEC > 0:
        conn.execute("DELETE FROM live_evidence_heartbeats WHERE received_at < ?", (current - LIVE_EVIDENCE_RETENTION_SEC,))
    if RAW_UPLOAD_RETENTION_SEC > 0:
        conn.execute("DELETE FROM raw_run_uploads WHERE approved=0 AND received_at < ?", (current - RAW_UPLOAD_RETENTION_SEC,))
    if TRUST_EVENT_RETENTION_SEC > 0:
        conn.execute("DELETE FROM trust_events WHERE created_at < ?", (current - TRUST_EVENT_RETENTION_SEC,))


def get_path(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def normalize_player_name(value: Any) -> str:
    if not value:
        return "unknown"
    return str(value).strip().replace(" ", "").lower()


def final_run_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    run = payload.get("run")
    if not isinstance(run, dict):
        raise HTTPException(status_code=400, detail="missing run object")
    return run


def evidence_run_id_from_run(run: dict[str, Any]) -> str:
    candidates = [
        run.get("evidenceRunId"),
        get_path(run, "syncEnrichment", "evidenceRunId"),
        get_path(run, "flags", "evidenceRunId"),
        run.get("runId"),
        run.get("run_id"),
    ]
    for c in candidates:
        if c:
            return str(c)
    # Deterministic fallback for old clients.
    seed = f"{run.get('startedAt')}|{run.get('completedAt')}|{run.get('dungeonId')}|{run.get('keyLevel')}"
    return "fallback-" + sha256_text(seed)[:24]


def client_run_id(run: dict[str, Any]) -> str:
    return str(run.get("runId") or run.get("run_id") or evidence_run_id_from_run(run))


def log_trust_event(conn: sqlite3.Connection, severity: str, event_type: str, uploader_id: str, session_id: str, evidence_run_id: str, message: str, details: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO trust_events
        (created_at,severity,event_type,uploader_id,session_id,evidence_run_id,message,details_json)
        VALUES (?,?,?,?,?,?,?,?)""",
        (now(), severity, event_type, uploader_id, session_id, evidence_run_id, message, canon(details)),
    )


@dataclass
class Validation:
    approved: bool
    verdict: str
    reason: str
    confidence: int
    details: dict[str, Any]


def load_heartbeats(conn: sqlite3.Connection, evidence_run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT payload_json, continuity, heartbeat_seq, heartbeat_chain_hash, prev_heartbeat_chain_hash, status, received_at
           FROM live_evidence_heartbeats
           WHERE evidence_run_id=?
           ORDER BY heartbeat_seq ASC, id ASC""",
        (evidence_run_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
        except Exception:
            continue
        p["_db"] = {
            "continuity": r["continuity"],
            "heartbeatSeq": r["heartbeat_seq"],
            "heartbeatChainHash": r["heartbeat_chain_hash"],
            "prevHeartbeatChainHash": r["prev_heartbeat_chain_hash"],
            "status": r["status"],
            "receivedAt": r["received_at"],
        }
        out.append(p)
    return out


def validate_heartbeat_chain(heartbeats: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    prev_hash = ""
    prev_seq = 0
    seen: set[int] = set()
    for hb_payload in heartbeats:
        hb = hb_payload.get("heartbeat") or {}
        te = hb.get("tamperEvidence") or {}
        seq = as_int(te.get("heartbeatSeq"), 0)
        current = str(te.get("heartbeatChainHash") or "")
        claimed_prev = str(te.get("prevHeartbeatChainHash") or "")
        if seq in seen:
            issues.append(f"duplicate heartbeatSeq={seq}")
        seen.add(seq)
        if seq <= prev_seq:
            issues.append(f"non-increasing heartbeatSeq {seq} after {prev_seq}")
        if prev_hash and claimed_prev != prev_hash:
            issues.append(f"heartbeat chain mismatch at seq={seq}")
        if not current or len(current) < 32:
            issues.append(f"missing/weak heartbeatChainHash at seq={seq}")
        prev_hash = current
        prev_seq = seq
    return (not issues), issues


def aggregate_final_run(run: dict[str, Any]) -> dict[str, Any]:
    players = run.get("players") if isinstance(run.get("players"), list) else []
    total_damage = as_int(run.get("totalDamage"), 0)
    deaths = as_int(run.get("deaths"), 0)
    interrupts = as_int(run.get("interrupts"), 0)
    if total_damage <= 0 and players:
        total_damage = sum(as_int(p.get("totalDamage", p.get("damage")), 0) for p in players if isinstance(p, dict))
    if deaths <= 0 and players:
        deaths = sum(as_int(p.get("deaths"), 0) for p in players if isinstance(p, dict))
    if interrupts <= 0 and players:
        interrupts = sum(as_int(p.get("interrupts"), 0) for p in players if isinstance(p, dict))
    duration = max(1, as_int(run.get("durationSec"), as_int(run.get("completedAt"), 0) - as_int(run.get("startedAt"), 0)))
    avg_dps = as_int(run.get("avgGroupDps"), total_damage // duration if duration else 0)
    return {
        "totalDamage": total_damage,
        "deaths": deaths,
        "interrupts": interrupts,
        "durationSec": duration,
        "avgGroupDps": avg_dps,
        "players": players,
    }


def validate_final_run_against_live(conn: sqlite3.Connection, payload: dict[str, Any], uploader_id: str) -> Validation:
    run = final_run_from_payload(payload)
    evidence_id = evidence_run_id_from_run(run)
    hbs = load_heartbeats(conn, evidence_id)
    final = aggregate_final_run(run)
    details: dict[str, Any] = {
        "evidenceRunId": evidence_id,
        "clientRunId": client_run_id(run),
        "heartbeatCount": len(hbs),
        "final": {k: final[k] for k in ["totalDamage", "deaths", "interrupts", "durationSec", "avgGroupDps"]},
    }
    if not hbs:
        return Validation(False, "not_approved_no_live_evidence", "no live heartbeat evidence for this run", 20, details)

    chain_ok, chain_issues = validate_heartbeat_chain(hbs)
    details["chainIssues"] = chain_issues
    if not chain_ok:
        return Validation(False, "rejected_chain_mismatch", "live heartbeat hash-chain continuity failed", 0, details)

    last_payload = hbs[-1]
    last_hb = last_payload.get("heartbeat") or {}
    details["lastHeartbeat"] = {
        "status": last_hb.get("status"),
        "totalDamage": as_int(last_hb.get("totalDamage"), 0),
        "deaths": as_int(last_hb.get("deaths"), 0),
        "interrupts": as_int(last_hb.get("interrupts"), 0),
        "completed": bool(last_hb.get("completed")),
        "abandoned": bool(last_hb.get("abandoned")),
        "startedAt": as_int(last_hb.get("startedAt"), 0),
        "completedAt": as_int(last_hb.get("completedAt"), 0),
    }

    if bool(last_hb.get("abandoned")):
        return Validation(False, "not_approved_abandoned", "live evidence says the key was abandoned/reset", 30, details)

    if not bool(last_hb.get("completed")) and str(last_hb.get("status")) not in {"completed"}:
        return Validation(False, "not_approved_incomplete_or_disconnect", "no completed live marker; keep as evidence, not public performance", 35, details)

    live_damage = as_int(last_hb.get("totalDamage"), 0)
    live_deaths = as_int(last_hb.get("deaths"), 0)
    live_interrupts = as_int(last_hb.get("interrupts"), 0)
    drift_allowed = max(10, int(max(live_damage, final["totalDamage"]) * MAX_FINAL_VS_LIVE_DAMAGE_DRIFT_RATIO))
    damage_delta = abs(final["totalDamage"] - live_damage)
    details["drift"] = {"damageDelta": damage_delta, "damageAllowed": drift_allowed}
    if live_damage > 0 and damage_delta > drift_allowed:
        return Validation(False, "rejected_final_mismatch", "final run damage does not match live evidence", 5, details)
    if final["deaths"] < live_deaths:
        return Validation(False, "rejected_death_count_lower_than_live", "final run has fewer deaths than live evidence", 5, details)
    if final["interrupts"] > live_interrupts + 3 and len(hbs) >= 2:
        return Validation(False, "suspicious_interrupt_count_higher_than_live", "final run has far more interrupts than live evidence", 25, details)

    confidence = 80
    if len(hbs) >= 2:
        confidence += 10
    if len(hbs) >= 4:
        confidence += 5
    if str(last_hb.get("status")) == "completed":
        confidence += 5
    confidence = min(100, confidence)
    if len(hbs) < MIN_HEARTBEATS_FOR_APPROVAL:
        return Validation(False, "not_approved_insufficient_heartbeat_coverage", "not enough live heartbeat coverage", min(confidence, 50), details)
    return Validation(True, "approved_verified_live", "verified by live evidence hash-chain", confidence, details)


def persist_approved_run(conn: sqlite3.Connection, payload: dict[str, Any], validation: Validation, uploader_id: str) -> None:
    run = final_run_from_payload(payload)
    final = aggregate_final_run(run)
    evidence_id = evidence_run_id_from_run(run)
    p_hash = payload_hash(payload)
    conn.execute(
        """INSERT OR IGNORE INTO approved_runs
        (approved_at,uploader_id,client_run_id,evidence_run_id,dungeon,dungeon_id,key_level,started_at,completed_at,duration_sec,total_damage,deaths,interrupts,avg_group_dps,confidence,trust_status,players_json,source_payload_hash)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            now(), uploader_id, client_run_id(run), evidence_id, str(run.get("dungeon") or run.get("dungeonName") or f"map_{run.get('dungeonId') or 0}"),
            as_int(run.get("dungeonId"), 0), as_int(run.get("keyLevel"), 0), as_int(run.get("startedAt"), 0), as_int(run.get("completedAt"), 0),
            final["durationSec"], final["totalDamage"], final["deaths"], final["interrupts"], final["avgGroupDps"], validation.confidence, validation.verdict,
            json.dumps(final["players"], ensure_ascii=False, separators=(",", ":")), p_hash,
        ),
    )


def insert_raw_upload(conn: sqlite3.Connection, payload: dict[str, Any], validation: Validation, uploader_id: str) -> None:
    run = final_run_from_payload(payload)
    conn.execute(
        """INSERT INTO raw_run_uploads
        (received_at,uploader_id,client_run_id,evidence_run_id,payload_hash,payload_json,verdict,approved,reason,validation_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            now(), uploader_id, client_run_id(run), evidence_run_id_from_run(run), payload_hash(payload),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), validation.verdict, 1 if validation.approved else 0, validation.reason,
            json.dumps(validation.details, ensure_ascii=False, separators=(",", ":")),
        ),
    )


@router.post("/api/v1/live-evidence/heartbeat")
async def live_evidence_heartbeat(request: Request):
    payload = await request.json()
    if payload.get("schemaVersion") != "mplusform_live_evidence_v1":
        raise HTTPException(status_code=400, detail="bad schemaVersion")
    uploader = payload.get("uploader") or {}
    hb = payload.get("heartbeat") or {}
    te = hb.get("tamperEvidence") or {}
    if not isinstance(hb, dict) or not isinstance(te, dict):
        raise HTTPException(status_code=400, detail="missing heartbeat tamperEvidence")
    session_id = str(hb.get("sessionId") or "")
    evidence_id = str(hb.get("evidenceRunId") or "")
    if not session_id or not evidence_id:
        raise HTTPException(status_code=400, detail="missing sessionId/evidenceRunId")
    seq = as_int(te.get("heartbeatSeq"), 0)
    if seq <= 0:
        raise HTTPException(status_code=400, detail="missing heartbeatSeq")
    uploader_id = str(uploader.get("id") or request.headers.get("X-MPlusForm-Uploader") or "unknown")
    current_chain = str(te.get("heartbeatChainHash") or "")
    prev_chain = str(te.get("prevHeartbeatChainHash") or "")
    combat_chain = str(te.get("combatLogChainHash") or "")
    if not current_chain:
        raise HTTPException(status_code=400, detail="missing heartbeatChainHash")

    with db() as conn:
        maybe_cleanup_old_evidence(conn)
        prev = conn.execute(
            "SELECT heartbeat_chain_hash, heartbeat_seq FROM live_evidence_heartbeats WHERE session_id=? ORDER BY heartbeat_seq DESC, id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        continuity = "first"
        if prev:
            continuity = "ok" if str(prev["heartbeat_chain_hash"] or "") == prev_chain else "mismatch"
        conn.execute(
            """INSERT OR IGNORE INTO live_evidence_heartbeats
            (received_at,uploader_id,session_id,evidence_run_id,status,heartbeat_seq,combatlog_chain_hash,heartbeat_chain_hash,prev_heartbeat_chain_hash,payload_hash,payload_json,continuity)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now(), uploader_id, session_id, evidence_id, str(hb.get("status") or "unknown"), seq, combat_chain, current_chain, prev_chain,
                payload_hash(payload), json.dumps(payload, ensure_ascii=False, separators=(",", ":")), continuity,
            ),
        )
        if continuity == "mismatch":
            log_trust_event(conn, "high", "heartbeat_chain_mismatch", uploader_id, session_id, evidence_id, "heartbeat chain mismatch", {"seq": seq, "prevChain": prev_chain})
    return {"ok": True, "version": VERSION, "sessionId": session_id, "evidenceRunId": evidence_id, "heartbeatSeq": seq, "continuity": continuity}


@router.post("/api/v1/runs")
async def trusted_runs_endpoint(request: Request):
    payload = await request.json()
    if payload.get("schemaVersion") != "mplusform_run_v1":
        raise HTTPException(status_code=400, detail="bad schemaVersion")
    uploader = payload.get("uploader") or {}
    uploader_id = str(uploader.get("id") or request.headers.get("X-MPlusForm-Uploader") or "unknown")
    with db() as conn:
        maybe_cleanup_old_evidence(conn)
        validation = validate_final_run_against_live(conn, payload, uploader_id)
        insert_raw_upload(conn, payload, validation, uploader_id)
        if validation.approved:
            persist_approved_run(conn, payload, validation, uploader_id)
        else:
            run = final_run_from_payload(payload)
            log_trust_event(conn, "medium" if validation.confidence > 0 else "high", validation.verdict, uploader_id, "", evidence_run_id_from_run(run), validation.reason, validation.details)
    return {
        "ok": True,
        "version": VERSION,
        "approved": validation.approved,
        "verdict": validation.verdict,
        "reason": validation.reason,
        "confidence": validation.confidence,
        "runId": validation.details.get("clientRunId"),
        "evidenceRunId": validation.details.get("evidenceRunId"),
    }


def build_profiles(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM approved_runs ORDER BY approved_at DESC LIMIT 5000").fetchall()
    by_player: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            players = json.loads(row["players_json"] or "[]")
        except Exception:
            players = []
        for p in players:
            if not isinstance(p, dict):
                continue
            name = normalize_player_name(p.get("nameRealm") or p.get("name") or p.get("guid"))
            if not name or name == "unknown":
                continue
            item = {
                "approvedAt": row["approved_at"],
                "dungeon": row["dungeon"],
                "keyLevel": row["key_level"],
                "durationSec": row["duration_sec"],
                "damage": as_int(p.get("totalDamage", p.get("damage")), 0),
                "deaths": as_int(p.get("deaths"), 0),
                "interrupts": as_int(p.get("interrupts"), 0),
                "confidence": row["confidence"],
            }
            by_player.setdefault(name, []).append(item)
    profiles: dict[str, Any] = {}
    for name, runs in by_player.items():
        runs.sort(key=lambda x: int(x["approvedAt"]), reverse=True)
        last5 = runs[:5]
        total_duration = max(1, sum(as_int(r.get("durationSec"), 0) for r in last5))
        total_damage = sum(as_int(r.get("damage"), 0) for r in last5)
        key_levels = [as_int(r.get("keyLevel"), 0) for r in last5]
        best_dps = max((int(as_int(r.get("damage"), 0) / max(1, as_int(r.get("durationSec"), 0))) for r in last5), default=0)
        profiles[name] = {
            "serverApproved": True,
            "nameKey": name,
            "last5Count": len(last5),
            "last5AvgDps": int(total_damage / total_duration),
            "bestDps": best_dps,
            "deathsAvg": round(sum(as_int(r.get("deaths"), 0) for r in last5) / max(1, len(last5)), 2),
            "interruptsAvg": round(sum(as_int(r.get("interrupts"), 0) for r in last5) / max(1, len(last5)), 2),
            "keyMin": min(key_levels) if key_levels else 0,
            "keyMax": max(key_levels) if key_levels else 0,
            "keyRange": [min(key_levels) if key_levels else 0, max(key_levels) if key_levels else 0],
            "confidence": int(sum(as_int(r.get("confidence"), 0) for r in last5) / max(1, len(last5))),
            "updatedAt": int(last5[0]["approvedAt"]) if last5 else 0,
            "runs": last5,
        }
    return profiles


def build_snapshot() -> dict[str, Any]:
    with db() as conn:
        profiles = build_profiles(conn)
        meta = {
            "schemaVersion": "mplusform_snapshot_v1",
            "generatedAt": now(),
            "serverApproved": True,
            "source": "server-trust-layer",
            "trustLayerVersion": VERSION,
            "profileCount": len(profiles),
        }
        snapshot = {"meta": meta, "profiles": profiles}
        snapshot["signature"] = sign_payload({"meta": meta, "profiles": profiles})
        return snapshot


@router.get("/api/v1/snapshot.json")
async def snapshot_json():
    return build_snapshot()


@router.get("/api/v1/snapshot.lua", response_class=PlainTextResponse)
async def snapshot_lua():
    snapshot = build_snapshot()
    meta = dict(snapshot["meta"])
    meta["profiles"] = meta.get("profileCount", 0)
    lines = [
        "-- Generated by MPlusForm server trust layer. Do not edit locally.",
        "MPlusFormSnapshotMeta = " + lua_value(meta),
        "MPlusFormSnapshot = " + lua_value(snapshot["profiles"]),
        "MPlusFormSnapshotSignature = " + lua_value(snapshot["signature"]),
        "",
    ]
    return "\n".join(lines)


@router.get("/api/v1/stats")
async def stats():
    with db() as conn:
        live = conn.execute("SELECT COUNT(*) AS c FROM live_evidence_heartbeats").fetchone()["c"]
        raw = conn.execute("SELECT COUNT(*) AS c FROM raw_run_uploads").fetchone()["c"]
        approved = conn.execute("SELECT COUNT(*) AS c FROM approved_runs").fetchone()["c"]
        rejected = conn.execute("SELECT COUNT(*) AS c FROM raw_run_uploads WHERE approved=0").fetchone()["c"]
        profiles = len(build_profiles(conn))
        last = conn.execute("SELECT verdict, reason, received_at FROM raw_run_uploads ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "service": "mplusform-api",
        "trustLayerVersion": VERSION,
        "requireToken": False,
        "liveHeartbeats": live,
        "rawRuns": raw,
        "approvedRuns": approved,
        "approvedProfiles": profiles,
        "rejectedProfiles": rejected,
        "lastRun": dict(last) if last else None,
    }


@router.get("/api/v1/health/trust")
async def trust_health():
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"ok": True, "version": VERSION, "db": str(DB_PATH)}
