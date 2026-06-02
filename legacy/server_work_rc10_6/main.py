from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from mplusform_trust_layer import router as mplusform_trust_router


DATA_DIR = Path(os.getenv("MPLUSFORM_DATA_DIR", "/opt/mplusform/data"))
DB_PATH = DATA_DIR / "mplusform.sqlite"
TOKEN_FILE = Path(os.getenv("MPLUSFORM_TOKEN_FILE", "/opt/mplusform/token.txt"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MPlusForm API", version="1.4.2-rc10.6-server-trust")
app.include_router(mplusform_trust_router)


class RunUpload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    schema_version: str = Field(
        validation_alias=AliasChoices("schemaVersion", "schema_version", "schema")
    )
    addon_version: str | None = Field(
        default=None, validation_alias=AliasChoices("addonVersion", "addon_version")
    )
    uploader: dict[str, Any] | None = None
    run: dict[str, Any]


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploader_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                received_at INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                flags_json TEXT NOT NULL,
                client_info_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(uploader_id, run_id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                region TEXT NOT NULL,
                realm TEXT NOT NULL,
                dungeon_name TEXT,
                dungeon_id INTEGER,
                key_level INTEGER,
                duration_sec REAL,
                completed INTEGER NOT NULL DEFAULT 0,
                timestamp INTEGER,
                flags_json TEXT NOT NULL,
                first_seen_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploader_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                region TEXT NOT NULL,
                realm TEXT NOT NULL,
                name TEXT NOT NULL,
                player_key TEXT NOT NULL,
                class_name TEXT,
                spec_name TEXT,
                dungeon_name TEXT,
                dungeon_id INTEGER,
                key_level INTEGER,
                duration REAL,
                duration_sec REAL,
                completed_at INTEGER,
                total_damage INTEGER,
                dps REAL,
                deaths INTEGER,
                interrupts INTEGER,
                flags_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_run_players_key ON run_players(player_key, completed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_run_players_run ON run_players(run_id);
            CREATE TABLE IF NOT EXISTS profiles (
                player_key TEXT PRIMARY KEY,
                region TEXT NOT NULL,
                realm TEXT NOT NULL,
                name TEXT NOT NULL,
                avg_dps REAL NOT NULL,
                best_dps REAL NOT NULL,
                avg_deaths REAL NOT NULL,
                avg_interrupts REAL NOT NULL,
                key_min INTEGER,
                key_max INTEGER,
                runs_count INTEGER NOT NULL,
                confidence TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )
        ensure_columns(conn, "uploads", {"client_info_json": "TEXT NOT NULL DEFAULT '{}'"})
        ensure_columns(
            conn,
            "run_players",
            {
                "class_name": "TEXT",
                "spec_name": "TEXT",
                "duration_sec": "REAL",
            },
        )


init_db()


def configured_token() -> tuple[str, str]:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token, "file"
    except OSError:
        pass
    token = (
        os.getenv("MPLUSFORM_INGEST_TOKEN")
        or os.getenv("MPLUSFORM_TOKEN")
        or ""
    ).strip()
    if token:
        return token, "env"
    return "", "missing"


def require_auth(authorization: str | None, legacy_token: str | None) -> str:
    """
    Public product rule: normal users must not enter tokens.

    By default /api/v1/runs accepts public client uploads and relies on
    server-side validation/confidence instead of a shared user token.

    For private/dev deployments set MPLUSFORM_REQUIRE_TOKEN=1 to require
    Bearer or X-MPlusForm-Token.
    """
    require_token = os.getenv("MPLUSFORM_REQUIRE_TOKEN", "0").strip().lower() in {"1", "true", "yes"}
    if not require_token:
        return "public"
    expected, _source = configured_token()
    if not expected:
        raise HTTPException(503, "ingest token is not configured")
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    elif legacy_token:
        supplied = legacy_token.strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "bad token")
    return "token"


def pick(data: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = data.get(name)
        if value is not None:
            return value
    return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def clean_realm(realm: Any) -> str:
    text = str(realm or "Unknown").strip()
    return text.replace(" ", "") or "Unknown"


def clean_name(name: Any) -> str:
    text = str(name or "Unknown").strip()
    return text or "Unknown"


def split_name_realm(name_realm: str, fallback_realm: str) -> tuple[str, str]:
    if "-" in name_realm:
        name, realm = name_realm.split("-", 1)
        return clean_name(name), clean_realm(realm)
    return clean_name(name_realm), clean_realm(fallback_realm)


def player_key(region: str, realm: str, name: str) -> str:
    return f"{region}-{clean_realm(realm)}-{clean_name(name)}"


def normalize_run(run: dict[str, Any]) -> dict[str, Any]:
    region = str(pick(run, "region", default="EU") or "EU").upper()
    realm = clean_realm(pick(run, "realm", default="Unknown"))
    duration_sec = as_float(pick(run, "durationSec", "duration_sec", "duration"), 0.0)
    timestamp = as_int(
        pick(run, "timestamp", "completedAt", "completed_at", "endedAt", "ended_at"),
        int(time.time()),
    )
    dungeon_name = pick(run, "dungeon", "dungeonName", "dungeon_name")
    dungeon_id = as_int(pick(run, "dungeonId", "dungeon_id"), 0)
    key_level = as_int(pick(run, "keyLevel", "key_level"), 0)
    completed = as_bool(pick(run, "completed", "timed"), True)
    started_at = as_int(pick(run, "startedAt", "started_at"), 0)
    run_id = str(
        pick(
            run,
            "runId",
            "run_id",
            default=f"{region}:{realm}:{dungeon_name}:{key_level}:{started_at}:{timestamp}",
        )
    )

    players = []
    for raw_player in pick(run, "players", default=[]) or []:
        if not isinstance(raw_player, dict):
            continue
        fallback_name = pick(raw_player, "name", default="Unknown")
        fallback_realm = pick(raw_player, "realm", default=realm)
        name, player_realm = split_name_realm(
            str(pick(raw_player, "nameRealm", "name_realm", default=fallback_name)),
            str(fallback_realm),
        )
        explicit_key = pick(raw_player, "playerKey", "player_key")
        total_damage = as_int(pick(raw_player, "totalDamage", "total_damage"), 0)
        dps = total_damage / max(duration_sec, 1.0)
        players.append(
            {
                "name": name,
                "realm": player_realm,
                "player_key": str(explicit_key or player_key(region, player_realm, name)),
                "class_name": pick(raw_player, "class", "className", "class_name"),
                "spec_name": pick(raw_player, "spec", "specName", "spec_name"),
                "total_damage": total_damage,
                "dps": dps,
                "claimed_dps": as_float(pick(raw_player, "dps"), 0.0),
                "deaths": as_int(pick(raw_player, "deaths"), 0),
                "interrupts": as_int(pick(raw_player, "interrupts"), 0),
            }
        )

    return {
        "run_id": run_id,
        "region": region,
        "realm": realm,
        "dungeon_name": str(dungeon_name or ""),
        "dungeon_id": dungeon_id,
        "key_level": key_level,
        "duration_sec": duration_sec,
        "completed": completed,
        "timestamp": timestamp,
        "players": players,
        "flags": pick(run, "flags", default={}) or {},
    }


SUSPICIOUS_FLAGS = {
    "player_count_not_5",
    "duration_too_short",
    "duration_too_long",
    "zero_total_damage",
    "zero_player_damage",
    "claimed_dps_mismatch",
    "extreme_dps",
    "impossible_interrupts",
    "impossible_team_interrupts",
    "impossible_deaths",
}


def validate_and_flags(run: dict[str, Any]) -> list[str]:
    flags: set[str] = set()
    duration_sec = float(run["duration_sec"] or 0)
    players = run["players"]
    if duration_sec < 60:
        flags.add("duration_too_short")
    if duration_sec > 7200:
        flags.add("duration_too_long")
    if len(players) != 5:
        flags.add("player_count_not_5")
    if run["flags"].get("outsideIgnored"):
        flags.add("outside_events_ignored")
    if run["flags"].get("unmatchedDamage"):
        flags.add("unmatched_damage_present")

    total_damage = 0
    team_interrupts = 0
    for player in players:
        damage = int(player["total_damage"] or 0)
        total_damage += damage
        interrupts = int(player["interrupts"] or 0)
        deaths = int(player["deaths"] or 0)
        team_interrupts += interrupts
        if damage <= 0:
            flags.add("zero_player_damage")
        # Hard caps are deliberately conservative. They are not used to rank players;
        # they only prevent obviously edited SavedVariables from entering public snapshot.
        if interrupts > 80:
            flags.add("impossible_interrupts")
        if deaths > 30:
            flags.add("impossible_deaths")
        recomputed = float(player["dps"] or 0)
        claimed = float(player["claimed_dps"] or 0)
        if claimed and abs(claimed - recomputed) / max(recomputed, 1) > 0.10:
            flags.add("claimed_dps_mismatch")
        if recomputed > 10_000_000:
            flags.add("extreme_dps")
    if team_interrupts > 250:
        flags.add("impossible_team_interrupts")
    if total_damage <= 0:
        flags.add("zero_total_damage")
    if flags.intersection(SUSPICIOUS_FLAGS):
        flags.add("suspicious")
    return sorted(flags)


def sanitized_payload(payload: RunUpload, run: dict[str, Any], flags: list[str]) -> str:
    data = {
        "schemaVersion": payload.schema_version,
        "addonVersion": payload.addon_version,
        "uploader": payload.uploader or {},
        "run": {
            "runId": run["run_id"],
            "region": run["region"],
            "realm": run["realm"],
            "dungeon": run["dungeon_name"],
            "dungeonId": run["dungeon_id"],
            "keyLevel": run["key_level"],
            "durationSec": run["duration_sec"],
            "completed": run["completed"],
            "timestamp": run["timestamp"],
            "players": [
                {
                    "name": player["name"],
                    "realm": player["realm"],
                    "class": player["class_name"],
                    "spec": player["spec_name"],
                    "totalDamage": player["total_damage"],
                    "deaths": player["deaths"],
                    "interrupts": player["interrupts"],
                }
                for player in run["players"]
            ],
            "flags": flags,
        },
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def confidence_for_profile(flags: set[str], matching_uploads: int, runs_count: int) -> str:
    # Public tooltip is server-truth only. Locally edited SavedVariables may be uploaded,
    # but suspicious data is rejected from public snapshot.
    if flags.intersection(SUSPICIOUS_FLAGS) or "suspicious" in flags:
        return "rejected"
    if matching_uploads >= 2:
        return "high"
    if runs_count >= 3:
        return "medium"
    return "low"


def row_flags(row: sqlite3.Row) -> set[str]:
    try:
        return set(json.loads(row["flags_json"] or "[]"))
    except (TypeError, ValueError):
        return set()


def recent_distinct_rows(rows: list[sqlite3.Row], limit: int = 5) -> list[sqlite3.Row]:
    seen: set[str] = set()
    recent: list[sqlite3.Row] = []
    for row in rows:
        run_id = str(row["run_id"])
        if run_id in seen:
            continue
        seen.add(run_id)
        recent.append(row)
        if len(recent) >= limit:
            break
    return recent


def recalc_profiles(conn: sqlite3.Connection, keys: list[str]) -> None:
    for key in keys:
        all_rows = conn.execute(
            """
            SELECT * FROM run_players
            WHERE player_key=?
            ORDER BY completed_at DESC, id DESC
            """,
            (key,),
        ).fetchall()
        recent = recent_distinct_rows(all_rows, 5)
        if not recent:
            continue

        all_distinct = recent_distinct_rows(all_rows, 1_000_000)
        runs_count = len(all_distinct)
        avg_dps = sum(float(row["dps"] or 0) for row in recent) / len(recent)
        best_dps = max(float(row["dps"] or 0) for row in all_distinct)
        avg_deaths = sum(int(row["deaths"] or 0) for row in recent) / len(recent)
        avg_interrupts = sum(int(row["interrupts"] or 0) for row in recent) / len(recent)
        key_levels = [int(row["key_level"] or 0) for row in all_distinct if row["key_level"] is not None]

        recent_run_ids = [row["run_id"] for row in recent]
        matching_uploads = 1
        if recent_run_ids:
            placeholders = ",".join("?" for _ in recent_run_ids)
            matches = conn.execute(
                f"""
                SELECT run_id, COUNT(DISTINCT uploader_id) AS uploaders
                FROM run_players
                WHERE run_id IN ({placeholders})
                GROUP BY run_id
                """,
                recent_run_ids,
            ).fetchall()
            matching_uploads = max([int(row["uploaders"]) for row in matches] or [1])

        flags: set[str] = set()
        for row in recent:
            flags.update(row_flags(row))
        confidence = confidence_for_profile(flags, matching_uploads, runs_count)
        first = recent[0]
        conn.execute(
            """
            INSERT INTO profiles(
                player_key, region, realm, name, avg_dps, best_dps,
                avg_deaths, avg_interrupts, key_min, key_max,
                runs_count, confidence, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(player_key) DO UPDATE SET
                region=excluded.region,
                realm=excluded.realm,
                name=excluded.name,
                avg_dps=excluded.avg_dps,
                best_dps=excluded.best_dps,
                avg_deaths=excluded.avg_deaths,
                avg_interrupts=excluded.avg_interrupts,
                key_min=excluded.key_min,
                key_max=excluded.key_max,
                runs_count=excluded.runs_count,
                confidence=excluded.confidence,
                updated_at=excluded.updated_at
            """,
            (
                key,
                first["region"],
                first["realm"],
                first["name"],
                avg_dps,
                best_dps,
                avg_deaths,
                avg_interrupts,
                min(key_levels or [0]),
                max(key_levels or [0]),
                runs_count,
                confidence,
                int(time.time()),
            ),
        )


def stats_payload() -> dict[str, Any]:
    token, source = configured_token()
    with db() as conn:
        uploads = conn.execute("SELECT COUNT(*) AS c FROM uploads").fetchone()["c"]
        runs = conn.execute("SELECT COUNT(DISTINCT run_id) AS c FROM uploads").fetchone()["c"]
        profiles = conn.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]
        approved_profiles = conn.execute("SELECT COUNT(*) AS c FROM profiles WHERE confidence != 'rejected'").fetchone()["c"]
        rejected_profiles = conn.execute("SELECT COUNT(*) AS c FROM profiles WHERE confidence = 'rejected'").fetchone()["c"]
        players = conn.execute("SELECT COUNT(*) AS c FROM run_players").fetchone()["c"]
        latest = conn.execute("SELECT MAX(received_at) AS ts FROM uploads").fetchone()["ts"]
    return {
        "ok": True,
        "service": "mplusform-api",
        "uploads": uploads,
        "runs": runs,
        "profiles": profiles,
        "approvedProfiles": approved_profiles,
        "rejectedProfiles": rejected_profiles,
        "runPlayers": players,
        "latestUploadAt": latest,
        "authConfigured": bool(token),
        "tokenSource": source,
        "requireToken": os.getenv("MPLUSFORM_REQUIRE_TOKEN", "0").strip().lower() in {"1", "true", "yes"},
    }


def public_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "playerKey": row["player_key"],
        "region": row["region"],
        "realm": row["realm"],
        "name": row["name"],
        "last5AvgDps": row["avg_dps"],
        "bestDps": row["best_dps"],
        "deathsAvg": row["avg_deaths"],
        "interruptsAvg": row["avg_interrupts"],
        "keyMin": row["key_min"],
        "keyMax": row["key_max"],
        "runs": row["runs_count"],
        "confidence": row["confidence"],
        "serverApproved": row["confidence"] != "rejected",
        "updatedAt": row["updated_at"],
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    stats = stats_payload()
    return {
        "ok": True,
        "service": stats["service"],
        "uploads": stats["uploads"],
        "profiles": stats["profiles"],
        "authConfigured": stats["authConfigured"],
        "tokenSource": stats["tokenSource"],
    }


@app.get("/api/v1/health")
def health_v1() -> dict[str, Any]:
    return health()


@app.get("/api/v1/stats")
def stats() -> dict[str, Any]:
    return stats_payload()


@app.post("/api/v1/runs")
async def upload_run(
    payload: RunUpload,
    request: Request,
    authorization: str | None = Header(default=None),
    x_mplusform_token: str | None = Header(default=None),
    x_mplusform_uploader: str | None = Header(default=None),
) -> dict[str, Any]:
    auth_mode = require_auth(authorization, x_mplusform_token)
    if payload.schema_version != "mplusform_run_v1":
        raise HTTPException(400, "bad schema")

    run = normalize_run(payload.run)
    flags = validate_and_flags(run)
    uploader = (
        x_mplusform_uploader
        or (payload.uploader or {}).get("id")
        or (request.client.host if request.client else None)
        or "unknown"
    )
    uploader = str(uploader)
    received_at = int(time.time())
    changed_keys = [player["player_key"] for player in run["players"]]
    client_info_json = json.dumps(payload.uploader or {}, ensure_ascii=False, separators=(",", ":"))
    raw_json = sanitized_payload(payload, run, flags)
    flags_json = json.dumps(flags, separators=(",", ":"))

    with db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO uploads(
                    uploader_id, run_id, received_at, raw_json, flags_json, client_info_json
                )
                VALUES(?,?,?,?,?,?)
                """,
                (uploader, run["run_id"], received_at, raw_json, flags_json, client_info_json),
            )
        except sqlite3.IntegrityError:
            return {"ok": True, "duplicate": True, "runId": run["run_id"]}

        conn.execute(
            """
            INSERT INTO runs(
                run_id, region, realm, dungeon_name, dungeon_id, key_level,
                duration_sec, completed, timestamp, flags_json, first_seen_at, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                flags_json=excluded.flags_json,
                updated_at=excluded.updated_at
            """,
            (
                run["run_id"],
                run["region"],
                run["realm"],
                run["dungeon_name"],
                run["dungeon_id"],
                run["key_level"],
                run["duration_sec"],
                1 if run["completed"] else 0,
                run["timestamp"],
                flags_json,
                received_at,
                received_at,
            ),
        )

        for player in run["players"]:
            conn.execute(
                """
                INSERT INTO run_players(
                    uploader_id, run_id, region, realm, name, player_key,
                    class_name, spec_name, dungeon_name, dungeon_id, key_level,
                    duration, duration_sec, completed_at, total_damage, dps,
                    deaths, interrupts, flags_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    uploader,
                    run["run_id"],
                    run["region"],
                    player["realm"],
                    player["name"],
                    player["player_key"],
                    player["class_name"],
                    player["spec_name"],
                    run["dungeon_name"],
                    run["dungeon_id"],
                    run["key_level"],
                    run["duration_sec"],
                    run["duration_sec"],
                    run["timestamp"],
                    player["total_damage"],
                    player["dps"],
                    player["deaths"],
                    player["interrupts"],
                    flags_json,
                ),
            )
        recalc_profiles(conn, sorted(set(changed_keys)))

    return {
        "ok": True,
        "runId": run["run_id"],
        "players": len(changed_keys),
        "flags": flags,
        "authMode": auth_mode,
    }


@app.get("/api/v1/profile/{region}/{realm}/{name}")
def profile(region: str, realm: str, name: str) -> dict[str, Any]:
    key = player_key(region.upper(), realm, name)
    with db() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE player_key=?", (key,)).fetchone()
    if not row or row["confidence"] == "rejected":
        raise HTTPException(404, "server-approved profile not found")
    return public_profile(row)


@app.get("/api/v1/snapshot.json")
def snapshot_json() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE confidence != 'rejected' ORDER BY updated_at DESC LIMIT 200000"
        ).fetchall()
    profiles = {
        row["player_key"]: {
            "avgDps": row["avg_dps"],
            "bestDps": row["best_dps"],
            "deathsAvg": row["avg_deaths"],
            "interruptsAvg": row["avg_interrupts"],
            "keyMin": row["key_min"],
            "keyMax": row["key_max"],
            "runs": row["runs_count"],
            "confidence": row["confidence"],
            "serverApproved": True,
            "updatedAt": row["updated_at"],
        }
        for row in rows
    }
    return {
        "meta": {
            "version": int(time.time()),
            "generatedAt": int(time.time()),
            "profiles": len(profiles),
            "region": "EU",
        },
        "profiles": profiles,
    }


def lua_quote(value: str) -> str:
    return json.dumps(value)


@app.get("/api/v1/snapshot.lua", response_class=PlainTextResponse)
def snapshot_lua() -> str:
    data = snapshot_json()
    meta = data["meta"]
    out = [
        f"MPlusFormSnapshotMeta = {{ version = {meta['version']}, generatedAt = {meta['generatedAt']}, region = \"EU\", profiles = {meta['profiles']} }}",
        "MPlusFormSnapshot = {",
    ]
    for key, profile_data in data["profiles"].items():
        out.append(
            "  "
            + f"[{lua_quote(key)}] = {{ "
            + f"avgDps = {float(profile_data['avgDps']):.3f}, "
            + f"bestDps = {float(profile_data['bestDps']):.3f}, "
            + f"deathsAvg = {float(profile_data['deathsAvg']):.3f}, "
            + f"interruptsAvg = {float(profile_data['interruptsAvg']):.3f}, "
            + f"keyMin = {int(profile_data['keyMin'] or 0)}, "
            + f"keyMax = {int(profile_data['keyMax'] or 0)}, "
            + f"runs = {int(profile_data['runs'])}, "
            + f"confidence = {lua_quote(str(profile_data['confidence']))}, "
            + "serverApproved = true, "
            + f"updatedAt = {int(profile_data['updatedAt'])} "
            + "},"
        )
    out.append("}")
    return "\n".join(out) + "\n"
