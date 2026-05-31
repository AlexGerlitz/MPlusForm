#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

VERSION = "1.4.2-rc10.7-trust-validated-sync"
APP_NAME = "MPlusFormSync"

DAMAGE_EVENTS = {
    "SWING_DAMAGE": 9,
    "RANGE_DAMAGE": 12,
    "SPELL_DAMAGE": 12,
    "SPELL_PERIODIC_DAMAGE": 12,
    "DAMAGE_SHIELD": 12,
    "DAMAGE_SPLIT": 12,
}
INTERRUPT_EVENTS = {"SPELL_INTERRUPT"}
DEATH_EVENTS = {"UNIT_DIED", "UNIT_DESTROYED", "UNIT_DISSIPATES"}
PET_OWNER_EVENTS = {"SPELL_SUMMON"}
PET_OWNER_HINT_SPELL_IDS = {
    "83242",   # Call Pet
    "118455",  # Beast Cleave pet buff
    "136",     # Mend Pet
    "19577",   # Intimidation
    "24394",   # Intimidation pet aura
    "272790",  # Frenzy
    "290819",  # Mend Pet
}


def default_base_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    return Path.home() / ".local" / "share" / "mplusform-sync"


def default_config_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME / "config.json"
    return Path.home() / ".config" / "mplusform-sync" / "config.json"


BASE_DIR = default_base_dir()
LOG_DIR = BASE_DIR / "logs"
STATE_PATH = BASE_DIR / "state.json"
DEFAULT_CONFIG = default_config_path()


class LuaParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0

    def parse_saved_variables(self) -> tuple[str, Any]:
        self.skip_ws()
        name = self.read_ident()
        self.skip_ws()
        self.expect("=")
        value = self.parse_value()
        return name, value

    def parse_value(self) -> Any:
        self.skip_ws()
        ch = self.peek()
        if ch == "{":
            return self.parse_table()
        if ch in {"'", '"'}:
            return self.read_string()
        if ch == "-" or ch.isdigit():
            return self.read_number()
        ident = self.read_ident()
        if ident == "true":
            return True
        if ident == "false":
            return False
        if ident == "nil":
            return None
        raise ValueError(f"unsupported Lua value {ident!r} at byte {self.i}")

    def parse_table(self) -> Any:
        self.expect("{")
        items: dict[Any, Any] = {}
        array_index = 1
        while True:
            self.skip_ws()
            if self.peek() == "}":
                self.i += 1
                break
            if self.peek() == "[":
                self.i += 1
                key = self.parse_value()
                self.skip_ws()
                self.expect("]")
                self.skip_ws()
                self.expect("=")
                value = self.parse_value()
            else:
                mark = self.i
                key = None
                try:
                    ident = self.read_ident()
                    self.skip_ws()
                    if self.peek() == "=":
                        self.i += 1
                        key = ident
                        value = self.parse_value()
                    else:
                        self.i = mark
                        value = self.parse_value()
                except ValueError:
                    self.i = mark
                    value = self.parse_value()
                if key is None:
                    key = array_index
                    array_index += 1
            items[key] = value
            self.skip_ws()
            if self.peek() in {",", ";"}:
                self.i += 1
        if items and all(isinstance(k, int) for k in items):
            keys = sorted(items)
            if keys == list(range(1, len(keys) + 1)):
                return [items[i] for i in keys]
        return items

    def skip_ws(self) -> None:
        while self.i < len(self.text):
            if self.text[self.i].isspace():
                self.i += 1
                continue
            if self.text.startswith("--", self.i):
                end = self.text.find("\n", self.i)
                self.i = len(self.text) if end == -1 else end + 1
                continue
            break

    def peek(self) -> str:
        return "" if self.i >= len(self.text) else self.text[self.i]

    def expect(self, ch: str) -> None:
        self.skip_ws()
        if self.peek() != ch:
            raise ValueError(f"expected {ch!r} at byte {self.i}, got {self.peek()!r}")
        self.i += 1

    def read_ident(self) -> str:
        self.skip_ws()
        start = self.i
        if self.i >= len(self.text) or not (self.text[self.i].isalpha() or self.text[self.i] == "_"):
            raise ValueError(f"expected identifier at byte {self.i}")
        self.i += 1
        while self.i < len(self.text) and (self.text[self.i].isalnum() or self.text[self.i] == "_"):
            self.i += 1
        return self.text[start:self.i]

    def read_string(self) -> str:
        quote = self.peek()
        self.i += 1
        out: list[str] = []
        while self.i < len(self.text):
            ch = self.text[self.i]
            self.i += 1
            if ch == quote:
                return "".join(out)
            if ch == "\\":
                if self.i >= len(self.text):
                    break
                esc = self.text[self.i]
                self.i += 1
                out.append({"n": "\n", "r": "\r", "t": "\t"}.get(esc, esc))
            else:
                out.append(ch)
        raise ValueError("unterminated string")

    def read_number(self) -> int | float:
        start = self.i
        if self.peek() == "-":
            self.i += 1
        while self.i < len(self.text) and (self.text[self.i].isdigit() or self.text[self.i] == "."):
            self.i += 1
        raw = self.text[start:self.i]
        return float(raw) if "." in raw else int(raw)


def lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def lua_key(key: Any) -> str:
    return f"[{key}]" if isinstance(key, int) else f"[{lua_string(str(key))}]"


def to_lua(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    child = " " * (indent + 2)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        for key in sorted(value, key=lambda k: str(k)):
            lines.append(f"{child}{lua_key(key)} = {to_lua(value[key], indent + 2)},")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "{}"
        lines = ["{"]
        for i, item in enumerate(value, 1):
            lines.append(f"{child}[{i}] = {to_lua(item, indent + 2)},")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "nil"
    return str(value)


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    with (LOG_DIR / "sync.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def write_state(**updates: Any) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    state = read_state()
    state.update(updates)
    state["updatedAt"] = int(time.time())
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def normalize_path(path: str | os.PathLike[str] | None) -> Path | None:
    if not path:
        return None
    return Path(str(path).replace("/", os.sep)).expanduser()


def resolve_combat_log_path(config: dict[str, Any]) -> Path | None:
    configured = normalize_path(config.get("combat_log_path"))
    if configured and configured.exists():
        return configured

    candidates: list[Path] = []
    logs_dir = configured.parent if configured else None
    if logs_dir:
        candidates.append(logs_dir)
    wow_path = normalize_path(config.get("wow_path"))
    if wow_path:
        candidates.append(wow_path / "_retail_" / "Logs")

    seen: set[str] = set()
    newest: list[Path] = []
    for directory in candidates:
        key = str(directory).lower()
        if key in seen or not directory.exists():
            continue
        seen.add(key)
        newest.extend(p for p in directory.glob("WoWCombatLog*.txt") if p.is_file())
    if not newest:
        return configured
    newest.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return newest[0]


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"config not found: {path}")
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    required = ["server_url", "saved_variables", "addon_data_dir"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise SystemExit("missing config fields: " + ", ".join(missing))
    config.setdefault("uploader_id", os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "mplusform-sync")
    config.setdefault("poll_interval_sec", 10)
    config.setdefault("combat_log_tolerance_before_sec", 180)
    config.setdefault("combat_log_tolerance_after_sec", 360)
    config.setdefault("min_selected_log_events_for_upload", 1)
    config.setdefault("upload_metadata_without_combatlog", False)
    config.setdefault("enable_combatlog_evidence", True)
    config.setdefault("combatlog_evidence_grace_sec", 120)
    config.setdefault("combatlog_initial_scan_bytes", 128 * 1024 * 1024)
    config.setdefault("upload_recovered_completed_runs", True)
    config.setdefault("upload_recovered_incomplete_runs", False)
    config.setdefault("recovered_overlap_start_tolerance_sec", 45)
    config.setdefault("min_recovered_total_damage", 1)
    config.setdefault("live_heartbeat_enabled", True)
    config.setdefault("live_heartbeat_interval_sec", 10)  # fallback only; jitter range below is preferred
    config.setdefault("live_heartbeat_jitter_enabled", True)
    config.setdefault("live_heartbeat_min_sec", 5)
    config.setdefault("live_heartbeat_max_sec", 15)
    config.setdefault("live_heartbeat_endpoint", "/api/v1/live-evidence/heartbeat")
    config.setdefault("live_heartbeat_spool_enabled", True)
    config.setdefault("live_heartbeat_upload_enabled", True)
    config.setdefault("live_heartbeat_stale_after_sec", 180)
    config.setdefault("live_heartbeat_max_players", 5)
    config.setdefault("live_heartbeat_endpoint_error_silence_sec", 600)
    config.setdefault("wow_process_check_enabled", False)  # policy-hardened: never inspect WoW process by default
    config.setdefault("wow_process_names", ["Wow.exe", "WowT.exe", "World of Warcraft.exe"])
    if not config.get("combat_log_path") and config.get("wow_path"):
        config["combat_log_path"] = str(Path(config["wow_path"]) / "_retail_" / "Logs" / "WoWCombatLog.txt")
    return config


def init_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"config already exists: {path}")
    sample = {
        "server_url": "http://127.0.0.1:8015",
        "wow_path": "G:/World of Warcraft",
        "saved_variables": "G:/World of Warcraft/_retail_/WTF/Account/ACCOUNT/SavedVariables/MPlusForm.lua",
        "addon_data_dir": "G:/World of Warcraft/_retail_/Interface/AddOns/MPlusForm/Data",
        "combat_log_path": "G:/World of Warcraft/_retail_/Logs/WoWCombatLog.txt",
        "uploader_id": os.environ.get("COMPUTERNAME") or "mplusform-sync",
        "poll_interval_sec": 10,
        "silent": True,
        "combat_log_tolerance_before_sec": 180,
        "combat_log_tolerance_after_sec": 360,
        "upload_metadata_without_combatlog": False,
        "enable_combatlog_evidence": True,
        "combatlog_evidence_grace_sec": 120,
        "upload_recovered_completed_runs": True,
        "upload_recovered_incomplete_runs": False,
        "live_heartbeat_enabled": True,
        "live_heartbeat_interval_sec": 10,
        "live_heartbeat_jitter_enabled": True,
        "live_heartbeat_min_sec": 5,
        "live_heartbeat_max_sec": 15,
        "live_heartbeat_endpoint": "/api/v1/live-evidence/heartbeat",
        "live_heartbeat_spool_enabled": True,
        "live_heartbeat_upload_enabled": True,
        "live_heartbeat_stale_after_sec": 180,
        "wow_process_check_enabled": False,
        "live_heartbeat_max_players": 5,
    }
    path.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path)


def read_sv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"uploadQueue": []}
    name, value = LuaParser(path.read_text(encoding="utf-8-sig")).parse_saved_variables()
    if name != "MPlusFormDB" or not isinstance(value, dict):
        raise RuntimeError(f"unexpected SavedVariables root: {name}")
    value.setdefault("uploadQueue", [])
    return value


def write_sv(path: Path, db: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("MPlusFormDB = " + to_lua(db) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def queue_entries(queue: Any) -> list[dict[str, Any]]:
    if isinstance(queue, dict):
        items = [queue[k] for k in sorted(queue) if isinstance(queue[k], dict)]
    elif isinstance(queue, list):
        items = [x for x in queue if isinstance(x, dict)]
    else:
        return []
    return [x for x in items if not x.get("sent") and x.get("status") not in {"sent", "uploaded"}]


def http_json(method: str, url: str, token: str | None = None, body: dict[str, Any] | None = None, uploader_id: str | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": f"MPlusFormSync/{VERSION}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    # Server is currently no-user-token. This remains backward-compatible only if a token is explicitly supplied.
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if uploader_id:
        headers["X-MPlusForm-Uploader"] = uploader_id
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error: {exc}") from exc


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=25) as resp:
        tmp.write_bytes(resp.read())
    os.replace(tmp, target)


def digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_player_name(value: Any) -> str:
    if not value:
        return ""
    s = str(value).strip().strip('"')
    s = s.replace(" ", "")
    return s.lower()


def normalize_player_lookup_name(value: Any) -> str:
    key = normalize_player_name(value)
    for suffix in ("-eu", "-us", "-kr", "-tw", "-cn"):
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def bare_name(name_realm: str) -> str:
    return name_realm.split("-", 1)[0] if name_realm else name_realm


@dataclass
class PlayerMetric:
    nameRealm: str
    guid: str | None = None
    totalDamage: int = 0
    deaths: int = 0
    interrupts: int = 0
    damageEvents: int = 0
    deathEvents: int = 0
    interruptEvents: int = 0


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except Exception:
        return default


def combat_log_damage_amount(event: str, fields: list[str]) -> int:
    candidates = [DAMAGE_EVENTS.get(event, -1)]
    # Advanced combat logging inserts unit health/power/position fields before amount.
    if event == "SWING_DAMAGE":
        candidates.append(28)
    elif event in DAMAGE_EVENTS:
        candidates.append(31)
    for idx in candidates:
        if idx >= 0 and len(fields) > idx:
            amount = as_int(fields[idx], 0)
            if amount > 0:
                return amount
    return 0


def combat_log_epoch(ts: str, reference_epoch: float) -> float | None:
    # WoW combat logs may include either M/D H:M:S.mmm or M/D/YYYY H:M:S.mmm.
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?$", ts.strip())
    if not m:
        return None
    month, day, explicit_year, hour, minute, sec, frac = m.groups()
    ref = datetime.fromtimestamp(reference_epoch)
    micro = int((frac or "0")[:6].ljust(6, "0"))
    candidates: list[float] = []
    if explicit_year:
        y = int(explicit_year)
        years = [2000 + y if y < 100 else y]
    else:
        years = [ref.year - 1, ref.year, ref.year + 1]
    for year in years:
        try:
            dt = datetime(year, int(month), int(day), int(hour), int(minute), int(sec), micro)
        except ValueError:
            continue
        candidates.append(dt.timestamp())
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x - reference_epoch))


def split_combat_log_line(line: str, reference_epoch: float) -> tuple[float, list[str]] | None:
    # Example: 5/31 03:11:22.123  SPELL_DAMAGE,0x...,"Name-Realm",...
    m = re.match(r"^(\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s+(.+)$", line.rstrip("\n\r"))
    if not m:
        return None
    epoch = combat_log_epoch(m.group(1), reference_epoch)
    if epoch is None:
        return None
    try:
        fields = next(csv.reader([m.group(2)], quotechar='"', delimiter=',', escapechar='\\'))
    except Exception:
        return None
    if not fields:
        return None
    return epoch, fields


def build_player_indexes(run: dict[str, Any]) -> tuple[dict[str, PlayerMetric], dict[str, PlayerMetric], dict[str, PlayerMetric]]:
    by_key: dict[str, PlayerMetric] = {}
    by_guid: dict[str, PlayerMetric] = {}
    by_name: dict[str, PlayerMetric] = {}
    for player in run.get("players") or []:
        if not isinstance(player, dict):
            continue
        nr = str(player.get("nameRealm") or "")
        if not nr:
            name = str(player.get("name") or "")
            realm = str(player.get("realm") or "")
            nr = f"{name}-{realm}" if name and realm else name
        if not nr:
            continue
        metric = PlayerMetric(nameRealm=nr, guid=str(player.get("guid") or "") or None)
        key = normalize_player_name(nr)
        by_key[key] = metric
        by_name[normalize_player_name(nr)] = metric
        by_name[normalize_player_name(bare_name(nr))] = metric
        if player.get("name"):
            by_name[normalize_player_name(player.get("name"))] = metric
        if metric.guid:
            by_guid[metric.guid] = metric
    return by_key, by_guid, by_name


def identify_actor(guid: str | None, name: str | None, by_guid: dict[str, PlayerMetric], by_name: dict[str, PlayerMetric], pet_owner_by_guid: dict[str, PlayerMetric]) -> PlayerMetric | None:
    if guid and guid in by_guid:
        return by_guid[guid]
    if guid and guid in pet_owner_by_guid:
        return pet_owner_by_guid[guid]
    if name:
        return by_name.get(normalize_player_name(name)) or by_name.get(normalize_player_lookup_name(name))
    return None


def combat_log_flags(raw: str | None) -> int:
    try:
        return int(str(raw or "0"), 16)
    except Exception:
        return 0


def combat_log_is_friendly_pet_target(guid: str | None, flags: str | None) -> bool:
    if not is_pet_guid(guid):
        return False
    return bool(combat_log_flags(flags) & 0x1000)


def combat_log_is_pet_owner_hint(fields: list[str]) -> bool:
    event = fields[0] if fields else ""
    if event in PET_OWNER_EVENTS:
        return True
    spell_id = str(fields[9]) if len(fields) > 9 else ""
    return spell_id in PET_OWNER_HINT_SPELL_IDS


def enrich_run_from_combat_log(run: dict[str, Any], combat_log_path: Path, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    started = float(run.get("startedAt") or 0)
    completed = float(run.get("completedAt") or 0)
    if started <= 0 or completed <= 0 or completed < started:
        raise RuntimeError("run has invalid startedAt/completedAt; cannot map combat-log window")
    if not combat_log_path.exists():
        raise RuntimeError(f"combat log not found: {combat_log_path}. Enable Advanced Combat Logging / /combatlog and run /reload after key.")

    before = int(config.get("combat_log_tolerance_before_sec", 180))
    after = int(config.get("combat_log_tolerance_after_sec", 360))
    window_start = started - before
    window_end = completed + after
    by_key, by_guid, by_name = build_player_indexes(run)
    if not by_key:
        raise RuntimeError("run has empty roster; cannot enrich combat-log metrics")

    pet_owner_by_guid: dict[str, PlayerMetric] = {}
    death_last_seen: dict[str, float] = {}
    stats = {
        "combatLogPath": str(combat_log_path),
        "windowStart": int(window_start),
        "windowEnd": int(window_end),
        "playersIndexed": len(by_key),
        "linesScanned": 0,
        "linesInWindow": 0,
        "eventsInWindow": 0,
        "damageEvents": 0,
        "interruptEvents": 0,
        "deathEvents": 0,
        "petOwnerEvents": 0,
        "unmatchedDamageEvents": 0,
        "unmatchedDamageAmount": 0,
        "parseSkippedLines": 0,
    }

    # utf-8 is normal, but WoW can contain localized names. errors=replace is safer than failing the whole upload.
    with combat_log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stats["linesScanned"] += 1
            parsed = split_combat_log_line(line, started)
            if parsed is None:
                stats["parseSkippedLines"] += 1
                continue
            event_time, fields = parsed
            if event_time < window_start:
                continue
            if event_time > window_end:
                # CombatLog is chronological. Do not break hard in case file has old appended chunks, but this saves time for normal files.
                if stats["linesInWindow"] > 0:
                    break
                continue
            stats["linesInWindow"] += 1
            event = fields[0]
            stats["eventsInWindow"] += 1
            if len(fields) < 9:
                continue
            src_guid = fields[1] or None
            src_name = fields[2] or None
            dst_guid = fields[5] or None
            dst_name = fields[6] or None
            dst_flags = fields[7] if len(fields) > 7 else None

            source_player = identify_actor(src_guid, src_name, by_guid, by_name, pet_owner_by_guid)
            if source_player and dst_guid and combat_log_is_friendly_pet_target(dst_guid, dst_flags) and combat_log_is_pet_owner_hint(fields):
                if dst_guid not in pet_owner_by_guid:
                    stats["petOwnerEvents"] += 1
                pet_owner_by_guid[dst_guid] = source_player

            if event in PET_OWNER_EVENTS:
                owner = identify_actor(src_guid, src_name, by_guid, by_name, pet_owner_by_guid)
                if owner and dst_guid:
                    if dst_guid not in pet_owner_by_guid:
                        stats["petOwnerEvents"] += 1
                    pet_owner_by_guid[dst_guid] = owner
                continue

            if event in DAMAGE_EVENTS:
                actor = identify_actor(src_guid, src_name, by_guid, by_name, pet_owner_by_guid)
                amount = combat_log_damage_amount(event, fields)
                if amount <= 0:
                    continue
                if actor:
                    actor.totalDamage += amount
                    actor.damageEvents += 1
                    stats["damageEvents"] += 1
                else:
                    stats["unmatchedDamageEvents"] += 1
                    stats["unmatchedDamageAmount"] += amount
                continue

            if event in INTERRUPT_EVENTS:
                actor = identify_actor(src_guid, src_name, by_guid, by_name, pet_owner_by_guid)
                if actor:
                    actor.interrupts += 1
                    actor.interruptEvents += 1
                    stats["interruptEvents"] += 1
                continue

            if event in DEATH_EVENTS:
                actor = identify_actor(dst_guid, dst_name, by_guid, by_name, pet_owner_by_guid)
                if actor:
                    key = dst_guid or actor.nameRealm
                    last = death_last_seen.get(key, 0)
                    if event_time - last > 2.0:
                        actor.deaths += 1
                        actor.deathEvents += 1
                        stats["deathEvents"] += 1
                        death_last_seen[key] = event_time
                continue

    enriched = json.loads(json.dumps(run, ensure_ascii=False))
    players = []
    total_damage = 0
    total_deaths = 0
    total_interrupts = 0
    # Preserve original roster fields, replace measured fields.
    original_by_name: dict[str, dict[str, Any]] = {}
    for p in run.get("players") or []:
        if isinstance(p, dict):
            nr = p.get("nameRealm") or (f"{p.get('name')}-{p.get('realm')}" if p.get("name") and p.get("realm") else p.get("name"))
            if nr:
                original_by_name[normalize_player_name(nr)] = p
    for key, metric in by_key.items():
        old = dict(original_by_name.get(key, {}))
        old["nameRealm"] = old.get("nameRealm") or metric.nameRealm
        if "name" not in old and metric.nameRealm:
            old["name"] = bare_name(metric.nameRealm)
        old["totalDamage"] = int(metric.totalDamage)
        old["damage"] = int(metric.totalDamage)
        old["deaths"] = int(metric.deaths)
        old["interrupts"] = int(metric.interrupts)
        old["syncDamageEvents"] = int(metric.damageEvents)
        old["syncDeathEvents"] = int(metric.deathEvents)
        old["syncInterruptEvents"] = int(metric.interruptEvents)
        players.append(old)
        total_damage += metric.totalDamage
        total_deaths += metric.deaths
        total_interrupts += metric.interrupts
    players.sort(key=lambda p: int(p.get("totalDamage") or 0), reverse=True)
    enriched["players"] = players
    enriched["totalDamage"] = int(total_damage)
    enriched["deaths"] = int(total_deaths)
    enriched["interrupts"] = int(total_interrupts)
    duration = max(1.0, float(enriched.get("durationSec") or (completed - started) or 1))
    enriched["durationSec"] = duration
    enriched["avgGroupDps"] = int(total_damage / duration)
    flags = dict(enriched.get("flags") or {})
    flags.update({
        "syncCombatLogRequired": True,
        "syncCombatLogParsed": True,
        "syncCombatLogParserVersion": VERSION,
        "syncCombatLogPath": str(combat_log_path),
        "nativeCombatLog": False,
        "detailsRequired": False,
        "serverTruthOnly": True,
    })
    enriched["flags"] = flags
    enriched["syncEnrichment"] = {
        "version": VERSION,
        "parsedAt": int(time.time()),
        "source": "WoWCombatLog.txt",
        "stats": stats,
        "totals": {
            "totalDamage": int(total_damage),
            "deaths": int(total_deaths),
            "interrupts": int(total_interrupts),
            "avgGroupDps": int(total_damage / duration),
        },
    }
    stats["totalDamage"] = int(total_damage)
    stats["totalDeaths"] = int(total_deaths)
    stats["totalInterrupts"] = int(total_interrupts)
    return enriched, stats



CHALLENGE_START_EVENTS = {"CHALLENGE_MODE_START"}
CHALLENGE_END_EVENTS = {"CHALLENGE_MODE_END", "CHALLENGE_MODE_COMPLETED"}
CHALLENGE_ABORT_EVENTS = {"CHALLENGE_MODE_RESET"}


def is_player_guid(guid: str | None) -> bool:
    return bool(guid) and str(guid).startswith("Player-")


def is_pet_guid(guid: str | None) -> bool:
    return bool(guid) and (str(guid).startswith("Pet-") or str(guid).startswith("Creature-0-"))


def metric_key_for_actor(guid: str | None, name: str | None, pet_owner_by_guid: dict[str, str]) -> str | None:
    if guid and guid in pet_owner_by_guid:
        return pet_owner_by_guid[guid]
    if is_player_guid(guid):
        return str(guid)
    # Recovery mode is intentionally conservative: no player GUID means no public player metric.
    return None


def ensure_evidence_player(session: dict[str, Any], key: str, guid: str | None, name: str | None) -> dict[str, Any]:
    players = session.setdefault("playersByKey", {})
    p = players.get(key)
    if not isinstance(p, dict):
        p = {
            "guid": guid or key,
            "nameRealm": name or key,
            "name": bare_name(name or key),
            "totalDamage": 0,
            "damage": 0,
            "deaths": 0,
            "interrupts": 0,
            "syncDamageEvents": 0,
            "syncDeathEvents": 0,
            "syncInterruptEvents": 0,
        }
        players[key] = p
    if name and (not p.get("nameRealm") or p.get("nameRealm") == key):
        p["nameRealm"] = name
        p["name"] = bare_name(name)
    if guid and not p.get("guid"):
        p["guid"] = guid
    return p


def parse_challenge_fields(event: str, fields: list[str]) -> dict[str, Any]:
    nums: list[int] = []
    for raw in fields[1:]:
        s = str(raw).strip().strip('"')
        if re.fullmatch(r"-?\d+", s):
            try:
                nums.append(int(s))
            except Exception:
                pass
    dungeon_id = nums[0] if nums else 0
    key_level = 0
    for n in nums[1:] + nums[:1]:
        if 2 <= n <= 40:
            key_level = n
            break
    return {
        "event": event,
        "rawFields": fields[:20],
        "dungeonId": dungeon_id,
        "keyLevel": key_level,
    }


def new_evidence_session(event_time: float, fields: list[str]) -> dict[str, Any]:
    meta = parse_challenge_fields(fields[0], fields)
    start = int(event_time)
    return {
        "source": "WoWCombatLog.txt-live-evidence",
        "schemaVersion": "mplusform_combatlog_evidence_v1",
        "startedAt": start,
        "lastEventAt": start,
        "lastHeartbeatAt": 0,
        "lastHeartbeatDigest": "",
        "completedAt": None,
        "durationSec": 0,
        "dungeonId": meta.get("dungeonId") or 0,
        "dungeon": f"map_{meta.get('dungeonId') or 0}",
        "keyLevel": meta.get("keyLevel") or 0,
        "challengeStartRaw": meta,
        "challengeEndRaw": None,
        "completed": False,
        "abandoned": False,
        "playersByKey": {},
        "petOwnerByGuid": {},
        "stats": {
            "linesInSession": 0,
            "eventsInSession": 0,
            "damageEvents": 0,
            "deathEvents": 0,
            "interruptEvents": 0,
            "petOwnerEvents": 0,
            "unmatchedDamageEvents": 0,
            "unmatchedDamageAmount": 0,
            "challengeMarkers": 1,
        },
    }


def close_evidence_session(session: dict[str, Any], event_time: float, fields: list[str], completed: bool, abandoned: bool = False) -> dict[str, Any]:
    session["completedAt"] = int(event_time)
    session["lastEventAt"] = int(event_time)
    session["durationSec"] = max(1, int(event_time) - int(session.get("startedAt") or event_time))
    session["completed"] = bool(completed)
    session["abandoned"] = bool(abandoned)
    session["challengeEndRaw"] = parse_challenge_fields(fields[0], fields)
    session.setdefault("stats", {})["challengeMarkers"] = int(session.get("stats", {}).get("challengeMarkers") or 0) + 1
    return finalize_evidence_session_totals(session)


def finalize_evidence_session_totals(session: dict[str, Any]) -> dict[str, Any]:
    players_by_key = session.get("playersByKey") if isinstance(session.get("playersByKey"), dict) else None
    if players_by_key is not None:
        players = list(players_by_key.values())
    else:
        players = list(session.get("players") or []) if isinstance(session.get("players"), list) else []
    players.sort(key=lambda p: int(p.get("totalDamage") or 0), reverse=True)
    total_damage = sum(int(p.get("totalDamage") or 0) for p in players)
    total_deaths = sum(int(p.get("deaths") or 0) for p in players)
    total_interrupts = sum(int(p.get("interrupts") or 0) for p in players)
    duration = max(1, int(session.get("durationSec") or 1))
    session["players"] = players
    session["totalDamage"] = int(total_damage)
    session["deaths"] = int(total_deaths)
    session["interrupts"] = int(total_interrupts)
    session["avgGroupDps"] = int(total_damage / duration)
    # Do not persist the internal pet map forever after the session has closed.
    if players_by_key is not None:
        session.pop("petOwnerByGuid", None)
        session.pop("playersByKey", None)
    return session



def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def init_evidence_chain(session: dict[str, Any]) -> None:
    if session.get("evidenceChainHash"):
        return
    seed = {
        "schema": "mplusform_tamper_evidence_v1",
        "startedAt": int(session.get("startedAt") or 0),
        "dungeonId": as_int(session.get("dungeonId"), 0),
        "keyLevel": as_int(session.get("keyLevel"), 0),
        "source": "WoWCombatLog.txt_tail",
    }
    raw = json.dumps(seed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    session["evidenceSeq"] = int(session.get("evidenceSeq") or 0)
    session["evidenceChainHash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    session["evidenceChainSeed"] = seed


def update_evidence_chain(session: dict[str, Any], line_text: str, event_time: float, event_name: str) -> None:
    init_evidence_chain(session)
    seq = int(session.get("evidenceSeq") or 0) + 1
    prev = str(session.get("evidenceChainHash") or "")
    line_sha = hashlib.sha256(line_text.encode("utf-8", errors="replace")).hexdigest()
    material = {
        "prev": prev,
        "seq": seq,
        "lineSha256": line_sha,
        "eventAtMs": int(event_time * 1000),
        "event": str(event_name or ""),
    }
    raw = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    chain = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    session["evidenceSeq"] = seq
    session["evidenceChainHash"] = chain
    session["lastCombatLogLineSha256"] = line_sha
    session["lastEvidenceEventAt"] = int(event_time)
    session["lastEvidenceEvent"] = str(event_name or "")
    stats = session.setdefault("stats", {})
    stats["evidenceLinesHashed"] = int(stats.get("evidenceLinesHashed") or 0) + 1


def heartbeat_interval_bounds(config: dict[str, Any]) -> tuple[int, int]:
    min_sec = max(5, as_int(config.get("live_heartbeat_min_sec"), 5))
    max_sec = max(min_sec, as_int(config.get("live_heartbeat_max_sec"), 15))
    # Keep a sane ceiling. This is load smoothing, not anti-cheat evasion.
    max_sec = min(max_sec, 300)
    return min_sec, max_sec


def next_heartbeat_delay(config: dict[str, Any]) -> int:
    if bool(config.get("live_heartbeat_jitter_enabled", True)):
        lo, hi = heartbeat_interval_bounds(config)
        return random.randint(lo, hi)
    return max(5, as_int(config.get("live_heartbeat_interval_sec"), 10))


def canonical_heartbeat_chain_digest(payload: dict[str, Any]) -> str:
    heartbeat = json.loads(json.dumps(payload.get("heartbeat") or {}, ensure_ascii=False))
    te = dict(heartbeat.get("tamperEvidence") or {})
    te.pop("heartbeatDigest", None)
    te.pop("heartbeatChainHash", None)
    heartbeat["tamperEvidence"] = te
    raw = json.dumps(heartbeat, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def attach_heartbeat_chain(session: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    heartbeat = payload.setdefault("heartbeat", {})
    init_evidence_chain(session)
    hb_seq = int(session.get("heartbeatSeq") or 0) + 1
    prev_hb_chain = str(session.get("heartbeatChainHash") or "")
    heartbeat["tamperEvidence"] = {
        "schemaVersion": "mplusform_tamper_evidence_v1",
        "hashAlg": "sha256",
        "heartbeatSeq": hb_seq,
        "prevHeartbeatChainHash": prev_hb_chain,
        "combatLogEvidenceSeq": int(session.get("evidenceSeq") or 0),
        "combatLogChainHash": session.get("evidenceChainHash") or "",
        "lastCombatLogLineSha256": session.get("lastCombatLogLineSha256") or "",
        "lastEvidenceEventAt": session.get("lastEvidenceEventAt"),
        "lastEvidenceEvent": session.get("lastEvidenceEvent") or "",
        "tamperPolicy": "client_files_are_untrusted_server_must_compare_live_chain_vs_final_run",
    }
    digest_value = canonical_heartbeat_chain_digest(payload)
    hb_chain = hashlib.sha256((prev_hb_chain + "|" + digest_value).encode("utf-8")).hexdigest()
    heartbeat["tamperEvidence"]["heartbeatDigest"] = digest_value
    heartbeat["tamperEvidence"]["heartbeatChainHash"] = hb_chain
    session["heartbeatSeq"] = hb_seq
    session["heartbeatChainHash"] = hb_chain
    session["lastHeartbeatDigest"] = digest_value
    return payload

def evidence_apply_event(session: dict[str, Any], fields: list[str]) -> None:
    stats = session.setdefault("stats", {})
    stats["eventsInSession"] = int(stats.get("eventsInSession") or 0) + 1
    if len(fields) < 9:
        return
    event = fields[0]
    src_guid = fields[1] or None
    src_name = fields[2] or None
    dst_guid = fields[5] or None
    dst_name = fields[6] or None
    dst_flags = fields[7] if len(fields) > 7 else None
    pet_owner_by_guid = session.setdefault("petOwnerByGuid", {})

    if is_player_guid(src_guid) and dst_guid and combat_log_is_friendly_pet_target(dst_guid, dst_flags) and combat_log_is_pet_owner_hint(fields):
        if str(dst_guid) not in pet_owner_by_guid:
            stats["petOwnerEvents"] = int(stats.get("petOwnerEvents") or 0) + 1
        pet_owner_by_guid[str(dst_guid)] = str(src_guid)

    if event in PET_OWNER_EVENTS:
        owner_key = metric_key_for_actor(src_guid, src_name, pet_owner_by_guid)
        if owner_key and dst_guid:
            ensure_evidence_player(session, owner_key, src_guid, src_name)
            if str(dst_guid) not in pet_owner_by_guid:
                stats["petOwnerEvents"] = int(stats.get("petOwnerEvents") or 0) + 1
            pet_owner_by_guid[str(dst_guid)] = owner_key
        return

    if event in DAMAGE_EVENTS:
        actor_key = metric_key_for_actor(src_guid, src_name, pet_owner_by_guid)
        amount = combat_log_damage_amount(event, fields)
        if amount <= 0:
            return
        if actor_key:
            guid_for_player = src_guid
            name_for_player = src_name
            if src_guid and actor_key != str(src_guid):
                existing = session.setdefault("playersByKey", {}).get(actor_key)
                if isinstance(existing, dict):
                    guid_for_player = existing.get("guid") or actor_key
                    name_for_player = existing.get("nameRealm") or actor_key
                else:
                    guid_for_player = actor_key
                    name_for_player = actor_key
            p = ensure_evidence_player(session, actor_key, guid_for_player, name_for_player)
            p["totalDamage"] = int(p.get("totalDamage") or 0) + amount
            p["damage"] = p["totalDamage"]
            p["syncDamageEvents"] = int(p.get("syncDamageEvents") or 0) + 1
            stats["damageEvents"] = int(stats.get("damageEvents") or 0) + 1
        else:
            stats["unmatchedDamageEvents"] = int(stats.get("unmatchedDamageEvents") or 0) + 1
            stats["unmatchedDamageAmount"] = int(stats.get("unmatchedDamageAmount") or 0) + amount
        return

    if event in INTERRUPT_EVENTS:
        actor_key = metric_key_for_actor(src_guid, src_name, pet_owner_by_guid)
        if actor_key:
            guid_for_player = src_guid
            name_for_player = src_name
            if src_guid and actor_key != str(src_guid):
                existing = session.setdefault("playersByKey", {}).get(actor_key)
                if isinstance(existing, dict):
                    guid_for_player = existing.get("guid") or actor_key
                    name_for_player = existing.get("nameRealm") or actor_key
                else:
                    guid_for_player = actor_key
                    name_for_player = actor_key
            p = ensure_evidence_player(session, actor_key, guid_for_player, name_for_player)
            p["interrupts"] = int(p.get("interrupts") or 0) + 1
            p["syncInterruptEvents"] = int(p.get("syncInterruptEvents") or 0) + 1
            stats["interruptEvents"] = int(stats.get("interruptEvents") or 0) + 1
        return

    if event in DEATH_EVENTS:
        if is_player_guid(dst_guid):
            p = ensure_evidence_player(session, str(dst_guid), dst_guid, dst_name)
            p["deaths"] = int(p.get("deaths") or 0) + 1
            p["syncDeathEvents"] = int(p.get("syncDeathEvents") or 0) + 1
            stats["deathEvents"] = int(stats.get("deathEvents") or 0) + 1
        return


def run_window_from_run(run: dict[str, Any], source: str = "savedvariables") -> dict[str, Any] | None:
    try:
        started = int(float(run.get("startedAt") or 0))
        completed = int(float(run.get("completedAt") or 0))
    except Exception:
        return None
    if started <= 0 or completed <= 0:
        return None
    return {
        "source": source,
        "runId": str(run.get("runId") or run.get("id") or ""),
        "startedAt": started,
        "completedAt": completed,
        "dungeonId": as_int(run.get("dungeonId"), 0),
        "keyLevel": as_int(run.get("keyLevel"), 0),
        "at": int(time.time()),
    }


def compact_windows(windows: list[dict[str, Any]], limit: int = 1000) -> list[dict[str, Any]]:
    clean = [w for w in windows if isinstance(w, dict) and int(w.get("startedAt") or 0) > 0]
    clean.sort(key=lambda w: int(w.get("startedAt") or 0))
    return clean[-limit:]


def overlaps_known_window(session: dict[str, Any], windows: list[dict[str, Any]], tolerance: int) -> bool:
    s = int(session.get("startedAt") or 0)
    if s <= 0:
        return False
    dungeon_id = as_int(session.get("dungeonId"), 0)
    key_level = as_int(session.get("keyLevel"), 0)
    for w in windows:
        ws = int(w.get("startedAt") or 0)
        if abs(ws - s) > tolerance:
            continue
        wd = as_int(w.get("dungeonId"), 0)
        wk = as_int(w.get("keyLevel"), 0)
        if dungeon_id and wd and dungeon_id != wd:
            continue
        if key_level and wk and key_level != wk:
            continue
        return True
    return False


def evidence_run_id(session: dict[str, Any]) -> str:
    return "recovered:%s:%s:%s" % (
        as_int(session.get("dungeonId"), 0),
        as_int(session.get("keyLevel"), 0),
        int(session.get("startedAt") or 0),
    )


def build_recovered_payload(session: dict[str, Any], uploader_id: str) -> dict[str, Any]:
    run_id = evidence_run_id(session)
    players = session.get("players") if isinstance(session.get("players"), list) else []
    run = {
        "runId": run_id,
        "region": "unknown",
        "realm": "unknown",
        "dungeon": session.get("dungeon") or f"map_{session.get('dungeonId') or 0}",
        "dungeonId": as_int(session.get("dungeonId"), 0),
        "keyLevel": as_int(session.get("keyLevel"), 0),
        "durationSec": max(1, as_int(session.get("durationSec"), 1)),
        "completed": bool(session.get("completed")),
        "startedAt": int(session.get("startedAt") or 0),
        "completedAt": int(session.get("completedAt") or int(time.time())),
        "players": players,
        "totalDamage": as_int(session.get("totalDamage"), 0),
        "deaths": as_int(session.get("deaths"), 0),
        "interrupts": as_int(session.get("interrupts"), 0),
        "avgGroupDps": as_int(session.get("avgGroupDps"), 0),
        "flags": {
            "recoveredFromCombatLog": True,
            "savedVariablesMissingAtUpload": True,
            "antiAltF4Evidence": True,
            "nativeCombatLog": False,
            "detailsRequired": False,
            "serverTruthOnly": True,
            "requiresServerValidation": True,
            "confidenceInput": "combatlog_recovered_challenge_markers",
            "challengeStartRaw": session.get("challengeStartRaw"),
            "challengeEndRaw": session.get("challengeEndRaw"),
            "tamperEvidence": True,
            "combatLogEvidenceSeq": int(session.get("evidenceSeq") or 0),
            "combatLogChainHash": session.get("evidenceChainHash") or "",
            "heartbeatChainHash": session.get("heartbeatChainHash") or "",
        },
    }
    return {
        "schemaVersion": "mplusform_run_v1",
        "uploader": {"id": uploader_id, "client": "mplusform-sync", "version": VERSION},
        "run": run,
        "syncEnrichment": {
            "version": VERSION,
            "parsedAt": int(time.time()),
            "source": "WoWCombatLog.txt live evidence recovery",
            "stats": session.get("stats") or {},
            "tamperEvidence": {
                "schemaVersion": "mplusform_tamper_evidence_v1",
                "combatLogEvidenceSeq": int(session.get("evidenceSeq") or 0),
                "combatLogChainHash": session.get("evidenceChainHash") or "",
                "heartbeatSeq": int(session.get("heartbeatSeq") or 0),
                "heartbeatChainHash": session.get("heartbeatChainHash") or "",
                "serverMustRejectIfFinalDoesNotMatchLiveEvidence": True,
            },
            "totals": {
                "totalDamage": run["totalDamage"],
                "deaths": run["deaths"],
                "interrupts": run["interrupts"],
                "avgGroupDps": run["avgGroupDps"],
            },
        },
    }



LIVE_EVIDENCE_DIR = BASE_DIR / "evidence"


def is_wow_process_running(config: dict[str, Any]) -> bool | None:
    """Policy-hardened mode: do not inspect the WoW process list.

    We intentionally avoid process enumeration, memory reads, input hooks, or any
    other behavior that can look like bot/anti-cheat interaction. Disconnect /
    client-close detection is inferred from combat-log staleness and missing
    challenge completion markers only. None means unknown.
    """
    return None


def live_session_id(session: dict[str, Any]) -> str:
    return "live:%s:%s:%s" % (
        as_int(session.get("dungeonId"), 0),
        as_int(session.get("keyLevel"), 0),
        int(session.get("startedAt") or 0),
    )


def live_session_status(session: dict[str, Any], config: dict[str, Any], now: int | None = None) -> tuple[str, str]:
    now = int(now or time.time())
    if session.get("completed"):
        return "completed", "challenge_end_marker_seen"
    if session.get("abandoned"):
        return "abandoned", "challenge_reset_marker_seen"
    last = int(session.get("lastEventAt") or session.get("startedAt") or 0)
    stale_after = int(config.get("live_heartbeat_stale_after_sec", 180))
    if last > 0 and now - last >= stale_after:
        running = is_wow_process_running(config)
        if running is False:
            return "client_closed_or_disconnected", "wow_process_not_running_no_challenge_end_marker"
        return "stale_possible_disconnect", f"no_combatlog_events_for_{now - last}s"
    return "in_progress", "combatlog_active_or_recent"


def compact_live_players(session: dict[str, Any], max_players: int) -> list[dict[str, Any]]:
    tmp = json.loads(json.dumps(session, ensure_ascii=False))
    finalize_evidence_session_totals(tmp)
    players = list(tmp.get("players") or [])
    players.sort(key=lambda p: int(p.get("totalDamage") or 0), reverse=True)
    safe: list[dict[str, Any]] = []
    for p in players[:max(1, int(max_players))]:
        safe.append({
            "guid": p.get("guid"),
            "nameRealm": p.get("nameRealm"),
            "name": p.get("name"),
            "totalDamage": as_int(p.get("totalDamage"), 0),
            "damage": as_int(p.get("damage"), as_int(p.get("totalDamage"), 0)),
            "deaths": as_int(p.get("deaths"), 0),
            "interrupts": as_int(p.get("interrupts"), 0),
            "syncDamageEvents": as_int(p.get("syncDamageEvents"), 0),
            "syncDeathEvents": as_int(p.get("syncDeathEvents"), 0),
            "syncInterruptEvents": as_int(p.get("syncInterruptEvents"), 0),
        })
    return safe


def build_live_heartbeat_payload(session: dict[str, Any], config: dict[str, Any], uploader_id: str, kind: str = "heartbeat") -> dict[str, Any]:
    now = int(time.time())
    tmp = json.loads(json.dumps(session, ensure_ascii=False))
    finalize_evidence_session_totals(tmp)
    status_value, reason = live_session_status(tmp, config, now)
    max_players = int(config.get("live_heartbeat_max_players", 5))
    return {
        "schemaVersion": "mplusform_live_evidence_v1",
        "uploader": {"id": uploader_id, "client": "mplusform-sync", "version": VERSION},
        "heartbeat": {
            "kind": kind,
            "sessionId": live_session_id(tmp),
            "evidenceRunId": evidence_run_id(tmp),
            "status": status_value,
            "statusReason": reason,
            "heartbeatAt": now,
            "startedAt": int(tmp.get("startedAt") or 0),
            "lastEventAt": int(tmp.get("lastEventAt") or tmp.get("startedAt") or 0),
            "completedAt": tmp.get("completedAt"),
            "durationSec": max(1, as_int(tmp.get("durationSec"), now - int(tmp.get("startedAt") or now))),
            "dungeonId": as_int(tmp.get("dungeonId"), 0),
            "dungeon": tmp.get("dungeon") or f"map_{tmp.get('dungeonId') or 0}",
            "keyLevel": as_int(tmp.get("keyLevel"), 0),
            "completed": bool(tmp.get("completed")),
            "abandoned": bool(tmp.get("abandoned")),
            "totalDamage": as_int(tmp.get("totalDamage"), 0),
            "deaths": as_int(tmp.get("deaths"), 0),
            "interrupts": as_int(tmp.get("interrupts"), 0),
            "avgGroupDps": as_int(tmp.get("avgGroupDps"), 0),
            "players": compact_live_players(tmp, max_players),
            "stats": tmp.get("stats") or {},
            "flags": {
                "liveEvidence": True,
                "notPublicSnapshotInput": True,
                "notFinalRun": status_value not in {"completed"},
                "serverMustKeepSeparateFromApprovedRuns": True,
                "source": "WoWCombatLog.txt_tail",
                "nativeCombatLog": False,
                "detailsRequired": False,
                "tamperEvidence": True,
                "jitterHeartbeat": bool(config.get("live_heartbeat_jitter_enabled", True)),
            },
        },
    }


def canonical_heartbeat_digest(payload: dict[str, Any]) -> str:
    heartbeat = dict(payload.get("heartbeat") or {})
    # Do not include heartbeatAt in the change digest; we still upload every interval for liveness.
    heartbeat.pop("heartbeatAt", None)
    raw = json.dumps(heartbeat, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def append_live_spool(payload: dict[str, Any]) -> None:
    LIVE_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    with (LIVE_EVIDENCE_DIR / f"tamper-evident-live-heartbeat-{day}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def maybe_upload_live_heartbeat(config: dict[str, Any], server: str, token: str | None, uploader_id: str, session: dict[str, Any], kind: str = "heartbeat", dry_run: bool = False) -> dict[str, Any]:
    if not bool(config.get("live_heartbeat_enabled", True)):
        return {"enabled": False}
    now = int(time.time())
    force = kind in {"final", "abandoned", "completed", "stale"}
    next_at = int(session.get("nextHeartbeatAt") or 0)
    if not force and next_at > 0 and now < next_at:
        return {"enabled": True, "sent": False, "reason": "jitter_interval_not_elapsed", "nextIn": next_at - now, "nextHeartbeatAt": next_at}
    # First heartbeat for a new active session is immediate; following heartbeats use randomized jitter.
    payload = build_live_heartbeat_payload(session, config, uploader_id, kind=kind)
    payload = attach_heartbeat_chain(session, payload)
    digest_value = canonical_heartbeat_digest(payload)
    delay = next_heartbeat_delay(config)
    session["nextHeartbeatAt"] = now + delay
    if bool(config.get("live_heartbeat_spool_enabled", True)):
        append_live_spool(payload)
    session["lastHeartbeatAt"] = now
    session["lastHeartbeatDigest"] = digest_value
    session["lastHeartbeatJitterDelaySec"] = delay
    if dry_run:
        log(f"DRY-RUN live heartbeat {payload['heartbeat']['sessionId']} status={payload['heartbeat']['status']} totalDamage={payload['heartbeat']['totalDamage']}")
        return {"enabled": True, "sent": False, "dryRun": True, "payload": payload}
    if not bool(config.get("live_heartbeat_upload_enabled", True)):
        return {"enabled": True, "sent": False, "spooled": True, "reason": "upload_disabled"}
    endpoint = str(config.get("live_heartbeat_endpoint") or "/api/v1/live-evidence/heartbeat")
    endpoint_url = server + (endpoint if endpoint.startswith("/") else "/" + endpoint)
    state = read_state()
    last_endpoint_error_at = int(state.get("lastTamperEvidentEndpointErrorAt") or 0)
    silence = int(config.get("live_heartbeat_endpoint_error_silence_sec", 600))
    try:
        response = http_json("POST", endpoint_url, token=token, body=payload, uploader_id=uploader_id)
        session["lastHeartbeatUploadOkAt"] = now
        session["lastHeartbeatUploadError"] = None
        return {"enabled": True, "sent": True, "endpoint": endpoint_url, "response": response}
    except Exception as exc:
        session["lastHeartbeatUploadError"] = str(exc)
        session["lastHeartbeatUploadErrorAt"] = now
        # This endpoint may not exist yet on the VPS; do not spam the log every minute.
        if now - last_endpoint_error_at >= silence:
            log(f"live heartbeat upload failed/non-fatal: {exc}. Local evidence spool is still kept at {LIVE_EVIDENCE_DIR}")
            write_state(lastTamperEvidentEndpointErrorAt=now, lastTamperEvidentEndpointError=str(exc))
        return {"enabled": True, "sent": False, "endpoint": endpoint_url, "error": str(exc), "spooled": True}

def process_combatlog_evidence(config: dict[str, Any], server: str, token: str | None, uploader_id: str, sent_ids: set[str], uploaded_windows: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    if not bool(config.get("enable_combatlog_evidence", True)):
        return {"enabled": False}
    path = resolve_combat_log_path(config)
    if path is None or not path.exists():
        return {"enabled": True, "exists": False, "path": str(path or "")}

    state = read_state()
    cursor = state.get("combatLogCursor") if isinstance(state.get("combatLogCursor"), dict) else {}
    old_path = cursor.get("path")
    old_size = int(cursor.get("size") or 0)
    offset = int(cursor.get("offset") or 0)
    size = path.stat().st_size
    if old_path != str(path) or size < old_size or offset > size:
        initial = int(config.get("combatlog_initial_scan_bytes", 128 * 1024 * 1024))
        offset = max(0, size - initial)
    active = state.get("combatLogActiveSession") if isinstance(state.get("combatLogActiveSession"), dict) else None
    closed = state.get("combatLogClosedSessions") if isinstance(state.get("combatLogClosedSessions"), list) else []

    scanned = 0
    markers = 0
    parse_skipped = 0
    reference = time.time()
    with path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        for line in f:
            scanned += 1
            parsed = split_combat_log_line(line, reference)
            if parsed is None:
                parse_skipped += 1
                continue
            event_time, fields = parsed
            if not fields:
                continue
            event = fields[0]
            if active:
                active.setdefault("stats", {})["linesInSession"] = int(active.get("stats", {}).get("linesInSession") or 0) + 1
            if event in CHALLENGE_START_EVENTS:
                markers += 1
                if active:
                    # Previous challenge never closed cleanly: evidence only, not public metrics by default.
                    closed.append(close_evidence_session(active, event_time, ["CHALLENGE_MODE_RESET"], completed=False, abandoned=True))
                active = new_evidence_session(event_time, fields)
                update_evidence_chain(active, line, event_time, event)
                continue
            if event in CHALLENGE_END_EVENTS or event in CHALLENGE_ABORT_EVENTS:
                markers += 1
                if active:
                    update_evidence_chain(active, line, event_time, event)
                    completed = event in CHALLENGE_END_EVENTS
                    abandoned = event in CHALLENGE_ABORT_EVENTS
                    closed.append(close_evidence_session(active, event_time, fields, completed=completed, abandoned=abandoned))
                    active = None
                continue
            if active:
                update_evidence_chain(active, line, event_time, event)
                active["lastEventAt"] = int(event_time)
                evidence_apply_event(active, fields)
        offset = f.tell()

    now = int(time.time())
    grace = int(config.get("combatlog_evidence_grace_sec", 120))
    min_damage = int(config.get("min_recovered_total_damage", 1))
    overlap_tol = int(config.get("recovered_overlap_start_tolerance_sec", 45))
    uploaded = 0
    held = 0
    skipped = 0
    live_heartbeat_result = None
    if active:
        active = finalize_evidence_session_totals(active)
        status_value, _ = live_session_status(active, config, now)
        kind = "stale" if status_value in {"stale_possible_disconnect", "client_closed_or_disconnected"} else "heartbeat"
        live_heartbeat_result = maybe_upload_live_heartbeat(config, server, token, uploader_id, active, kind=kind, dry_run=dry_run)
    for session in closed:
        if not isinstance(session, dict):
            continue
        if session.get("uploaded") or session.get("skipped"):
            continue
        session = finalize_evidence_session_totals(session)
        rid = evidence_run_id(session)
        age = now - int(session.get("completedAt") or now)
        if age < grace:
            session["heldReason"] = f"waiting_grace_{grace}s_for_savedvariables"
            held += 1
            continue
        if overlaps_known_window(session, uploaded_windows, overlap_tol):
            session["skipped"] = True
            session["skipReason"] = "overlaps_savedvariables_or_previous_upload"
            skipped += 1
            continue
        if rid in sent_ids:
            session["skipped"] = True
            session["skipReason"] = "already_sent_run_id"
            skipped += 1
            continue
        if as_int(session.get("totalDamage"), 0) < min_damage:
            session["skipped"] = True
            session["skipReason"] = "below_min_recovered_total_damage"
            skipped += 1
            continue
        # Live evidence heartbeat is separate from public /runs. Send/spool final status even for incomplete keys.
        final_kind = "completed" if session.get("completed") else ("abandoned" if session.get("abandoned") else "final")
        hb = maybe_upload_live_heartbeat(config, server, token, uploader_id, session, kind=final_kind, dry_run=dry_run)
        if isinstance(hb, dict):
            session["lastTamperEvident"] = {k: v for k, v in hb.items() if k != "payload"}
        should_upload_completed = bool(config.get("upload_recovered_completed_runs", True)) and bool(session.get("completed"))
        should_upload_incomplete = bool(config.get("upload_recovered_incomplete_runs", False)) and not bool(session.get("completed"))
        if not (should_upload_completed or should_upload_incomplete):
            session["skipped"] = True
            session["skipReason"] = "incomplete_evidence_kept_local_not_uploaded"
            skipped += 1
            continue
        payload = build_recovered_payload(session, uploader_id)
        if dry_run:
            log(f"DRY-RUN would upload recovered combatlog run {rid}: players={len(payload['run'].get('players') or [])} totalDamage={payload['run'].get('totalDamage')}")
            held += 1
            continue
        try:
            response = http_json("POST", f"{server}/api/v1/runs", token=token, body=payload, uploader_id=uploader_id)
            session["uploaded"] = True
            session["uploadedAt"] = now
            session["serverRunId"] = response.get("runId") or response.get("run_id") or rid
            sent_ids.add(str(session["serverRunId"]))
            sent_ids.add(rid)
            win = run_window_from_run(payload["run"], source="combatlog_recovered")
            if win:
                uploaded_windows.append(win)
            uploaded += 1
            log(f"uploaded recovered combatlog run {session['serverRunId']} players={len(payload['run'].get('players') or [])} totalDamage={payload['run'].get('totalDamage')}")
        except Exception as exc:
            session["lastUploadError"] = str(exc)
            session["lastUploadErrorAt"] = now
            held += 1
            log(f"recovered combatlog upload failed for {rid}: {exc}")

    # Keep only useful recent evidence; this is local anti-abuse state, not public truth.
    closed = [s for s in closed if isinstance(s, dict)]
    closed.sort(key=lambda s: int(s.get("startedAt") or 0))
    closed = closed[-100:]
    return {
        "enabled": True,
        "exists": True,
        "path": str(path),
        "size": size,
        "offset": offset,
        "linesScanned": scanned,
        "parseSkippedLines": parse_skipped,
        "challengeMarkersSeen": markers,
        "activeSession": active,
        "closedSessions": closed,
        "uploadedRecovered": uploaded,
        "heldRecovered": held,
        "skippedRecovered": skipped,
        "updatedAt": now,
        "liveHeartbeat": live_heartbeat_result,
        "cursor": {"path": str(path), "size": size, "offset": offset},
    }


def maybe_enrich_run(run: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    flags = run.get("flags") if isinstance(run.get("flags"), dict) else {}
    needs_log = bool(flags.get("syncCombatLogRequired") or flags.get("captureMode") == "retail12-logfile-sync-required")
    if not needs_log:
        return run, None
    combat_log = resolve_combat_log_path(config)
    if combat_log is None:
        raise RuntimeError("combat_log_path is not configured")
    enriched, stats = enrich_run_from_combat_log(run, combat_log, config)
    min_events = int(config.get("min_selected_log_events_for_upload", 1))
    if stats.get("eventsInWindow", 0) < min_events:
        raise RuntimeError(f"combat log parsed, but no events found in run window. path={combat_log} window={stats.get('windowStart')}..{stats.get('windowEnd')}")
    if stats.get("totalDamage", 0) <= 0:
        raise RuntimeError(f"combat log parsed, but matched player damage is zero. Check Advanced Combat Logging, roster names/realm, and timestamp window. stats={stats}")
    return enriched, stats


def run_once(config: dict[str, Any], dry_run: bool = False) -> int:
    server = str(config["server_url"]).rstrip("/")
    token = str(config.get("token") or "") or None
    uploader_id = str(config["uploader_id"])
    sv_path = normalize_path(config["saved_variables"])
    if sv_path is None:
        raise RuntimeError("saved_variables path is not configured")
    data_dir = normalize_path(config["addon_data_dir"])
    if data_dir is None:
        raise RuntimeError("addon_data_dir path is not configured")
    state = read_state()
    sent_ids = {str(x) for x in state.get("sentRunIds", []) if x}
    uploaded_windows = list(state.get("uploadedRunWindows", []) if isinstance(state.get("uploadedRunWindows"), list) else [])
    db = read_sv(sv_path)
    entries = queue_entries(db.get("uploadQueue", []))
    uploaded = 0
    failed = 0
    skipped = 0
    last_enrichment: dict[str, Any] | None = None

    for entry in entries:
        run = entry.get("run", entry)
        if not isinstance(run, dict):
            skipped += 1
            continue
        run_id = run.get("runId") or run.get("run_id") or entry.get("id") or "<no-run-id>"
        run_id = str(run_id)
        if run_id in sent_ids:
            entry["sent"] = True
            entry["status"] = "sent"
            entry["serverRunId"] = run_id
            skipped += 1
            continue
        try:
            enriched_run, enrichment_stats = maybe_enrich_run(run, config)
            last_enrichment = enrichment_stats
        except Exception as exc:
            # For almost-production safety: do not upload incomplete Retail 12 metadata as if it was valid metrics.
            if not bool(config.get("upload_metadata_without_combatlog", False)):
                entry["lastUploadError"] = str(exc)
                entry["lastUploadErrorAt"] = int(time.time())
                entry["status"] = "pending"
                failed += 1
                log(f"enrichment failed for {run_id}: {exc}")
                continue
            enriched_run = run
            last_enrichment = {"error": str(exc), "metadataOnly": True}

        payload = {
            "schemaVersion": "mplusform_run_v1",
            "uploader": {"id": uploader_id, "client": "mplusform-sync", "version": VERSION},
            "run": enriched_run,
            "clientTrustPolicy": {
                "clientFilesAreUntrusted": True,
                "serverMustRecalculate": True,
                "serverMustCompareAgainstLiveEvidence": True,
                "savedVariablesMayBeEditedByUser": True,
                "combatLogMayBeEditedAfterRun": True,
            },
        }
        if last_enrichment is not None:
            payload["syncEnrichment"] = last_enrichment
        if dry_run:
            log(f"DRY-RUN would upload {run_id}: players={len(enriched_run.get('players') or [])} totalDamage={enriched_run.get('totalDamage')}")
            skipped += 1
            continue
        try:
            response = http_json("POST", f"{server}/api/v1/runs", token=token, body=payload, uploader_id=uploader_id)
            entry["sent"] = True
            entry["status"] = "sent"
            entry["sentAt"] = int(time.time())
            entry["serverRunId"] = response.get("runId") or response.get("run_id") or run_id
            entry["lastUploadError"] = None
            entry["lastSyncEnrichment"] = last_enrichment
            sent_ids.add(str(entry["serverRunId"]))
            sent_ids.add(run_id)
            win = run_window_from_run(enriched_run, source="savedvariables")
            if win:
                uploaded_windows.append(win)
            uploaded += 1
            log(f"uploaded {entry['serverRunId']} players={len(enriched_run.get('players') or [])} totalDamage={enriched_run.get('totalDamage')}")
        except Exception as exc:
            entry["lastUploadError"] = str(exc)
            entry["lastUploadErrorAt"] = int(time.time())
            failed += 1
            log(f"upload failed for {run_id}: {exc}")

    evidence_summary = process_combatlog_evidence(config, server, token, uploader_id, sent_ids, uploaded_windows, dry_run=dry_run)

    if not dry_run:
        write_sv(sv_path, db)
        try:
            download(f"{server}/api/v1/snapshot.lua", data_dir / "Snapshot.lua")
            download(f"{server}/api/v1/snapshot.json", data_dir / "Snapshot.json")
            log("snapshot downloaded")
        except Exception as exc:
            log(f"snapshot download failed: {exc}")
    remaining = len(queue_entries(db.get("uploadQueue", [])))
    write_state(
        version=VERSION,
        lastRunAt=int(time.time()),
        pending=remaining,
        uploaded=uploaded,
        failed=failed,
        skipped=skipped,
        server=server,
        savedVariables=str(sv_path),
        combatLogPath=str(resolve_combat_log_path(config) or ""),
        sentRunIds=sorted(sent_ids)[-5000:],
        uploadedRunWindows=compact_windows(uploaded_windows),
        combatLogCursor=evidence_summary.get("cursor") if isinstance(evidence_summary, dict) else {},
        combatLogActiveSession=evidence_summary.get("activeSession") if isinstance(evidence_summary, dict) else None,
        combatLogClosedSessions=evidence_summary.get("closedSessions") if isinstance(evidence_summary, dict) else [],
        lastCombatLogEvidence=evidence_summary,
        liveEvidenceDir=str(LIVE_EVIDENCE_DIR),
        lastEnrichment=last_enrichment,
    )
    return uploaded


def status(config_path: Path) -> int:
    print(f"MPlusForm Sync {VERSION}")
    print(f"Config: {config_path}")
    print(f"Logs: {LOG_DIR / 'sync.log'}")
    print(f"State: {STATE_PATH}")
    if config_path.exists():
        cfg = load_config(config_path)
        for key in ["server_url", "wow_path", "saved_variables", "addon_data_dir", "combat_log_path", "uploader_id", "poll_interval_sec", "enable_combatlog_evidence", "combatlog_evidence_grace_sec", "upload_recovered_completed_runs", "upload_recovered_incomplete_runs", "live_heartbeat_enabled", "live_heartbeat_interval_sec", "live_heartbeat_jitter_enabled", "live_heartbeat_min_sec", "live_heartbeat_max_sec", "live_heartbeat_endpoint", "live_heartbeat_upload_enabled", "live_heartbeat_spool_enabled", "live_heartbeat_stale_after_sec"]:
            if key in cfg:
                print(f"{key}: {cfg[key]}")
        token = cfg.get("token")
        print("auth: no-user-token" if not token else "auth: token configured")
        combat_log = resolve_combat_log_path(cfg)
        if combat_log:
            print(f"combat_log_resolved: {combat_log}")
            print(f"combat_log_exists: {combat_log.exists()} size={combat_log.stat().st_size if combat_log.exists() else 0}")
    if STATE_PATH.exists():
        print(STATE_PATH.read_text(encoding="utf-8"))
    return 0


def watch(config: dict[str, Any], once_immediately: bool = True) -> None:
    interval = max(10, int(config.get("poll_interval_sec", 60)))
    sv_path = normalize_path(config["saved_variables"])
    if sv_path is None:
        raise RuntimeError("saved_variables path is not configured")
    last = None
    log(f"MPlusForm Sync {VERSION} started, watching {sv_path}, interval={interval}s")
    if once_immediately:
        try:
            run_once(config)
        except Exception as exc:
            log(f"initial sync error: {exc}\n{traceback.format_exc()}")
    while True:
        try:
            d = digest(sv_path)
            if d != last:
                last = d
                run_once(config)
            else:
                # Even if SavedVariables did not change, keep live anti-AltF4 combat-log evidence moving.
                server = str(config["server_url"]).rstrip("/")
                token = str(config.get("token") or "") or None
                uploader_id = str(config["uploader_id"])
                state = read_state()
                sent_ids = {str(x) for x in state.get("sentRunIds", []) if x}
                uploaded_windows = list(state.get("uploadedRunWindows", []) if isinstance(state.get("uploadedRunWindows"), list) else [])
                evidence_summary = process_combatlog_evidence(config, server, token, uploader_id, sent_ids, uploaded_windows, dry_run=False)
                write_state(
                    version=VERSION,
                    lastEvidencePollAt=int(time.time()),
                    sentRunIds=sorted(sent_ids)[-5000:],
                    uploadedRunWindows=compact_windows(uploaded_windows),
                    combatLogCursor=evidence_summary.get("cursor") if isinstance(evidence_summary, dict) else {},
                    combatLogActiveSession=evidence_summary.get("activeSession") if isinstance(evidence_summary, dict) else None,
                    combatLogClosedSessions=evidence_summary.get("closedSessions") if isinstance(evidence_summary, dict) else [],
                    lastCombatLogEvidence=evidence_summary,
                    liveEvidenceDir=str(LIVE_EVIDENCE_DIR),
                )
        except Exception as exc:
            log(f"sync loop error: {exc}\n{traceback.format_exc()}")
            write_state(lastError=str(exc))
        time.sleep(interval)


def main() -> int:
    p = argparse.ArgumentParser(description="MPlusForm silent background sync, no-token, Retail 12 WoWCombatLog enrichment + policy-hardened live heartbeat evidence")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--init-config", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    config_path = args.config.expanduser()
    if args.init_config:
        init_config(config_path)
        return 0
    if args.status:
        return status(config_path)
    config = load_config(config_path)
    if args.dry_run:
        run_once(config, dry_run=True)
        return 0
    if args.once:
        run_once(config)
        return 0
    watch(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
