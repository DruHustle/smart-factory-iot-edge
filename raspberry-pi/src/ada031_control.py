"""Allowlisted control and telemetry adapter for Adeept ADA031 V4 firmware."""

from __future__ import annotations

import json
import math
import re
import time
from collections import OrderedDict
from threading import RLock
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


# The connected firmware retains these official V4 jog keys at 9600 baud.
COMMAND_BYTES = {
    ("base", "increase"): b"o",
    ("base", "decrease"): b"p",
    ("shoulder", "increase"): b"u",
    ("shoulder", "decrease"): b"i",
    ("elbow", "increase"): b"t",
    ("elbow", "decrease"): b"y",
    ("wrist_rotation", "increase"): b"e",
    ("wrist_rotation", "decrease"): b"r",
    ("gripper", "increase"): b"q",
    ("gripper", "decrease"): b"w",
}
LEGACY_COMMAND_FIELDS = {"schemaVersion", "action", "commandId", "targetAssetId", "joint", "direction", "expiresAt"}
COMMON_COMMAND_FIELDS = {"schemaVersion", "action", "commandId", "targetAssetId", "expiresAt"}
PROFILE_COMMAND_BYTES = {
    "pick_and_place_repeat": b"P",
    "demonstration_moves": b"D",
}
ACTION_COMMAND_BYTES = {
    "neutral": b"N",
    "stop_program": b"S",
}
SAFE_COMMAND_ID = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")
MAX_EPOCH_MILLISECONDS = 9_223_372_036_854_775_807
MIN_COMMAND_INTERVAL_SECONDS = 0.2
MAX_SERIAL_RECORD_BYTES = 4096

ADA031_COUNTER_SIGNALS = {
    "cycle_count", "successful_cycles", "failed_cycles", "interrupted_cycles",
    "cycle_time_ms", "uptime_ms",
}
ADA031_ENUM_SIGNALS = {"active_profile": (0, 2), "sequence_step": (0, 6)}
ADA031_BOOLEAN_SIGNALS = {"movement_active", "button_pressed", "calibration_mode", "pots_matched"}
ADA031_ANGLE_SIGNALS = {
    *(f"servo_{axis}_deg" for axis in range(1, 6)),
    *(f"pot_{axis}_deg" for axis in range(1, 6)),
}
ADA031_TELEMETRY_SIGNALS = (
    ADA031_COUNTER_SIGNALS | set(ADA031_ENUM_SIGNALS) | ADA031_BOOLEAN_SIGNALS | ADA031_ANGLE_SIGNALS
)


def resolve_command_byte(joint: str, direction: str) -> bytes:
    """Map a named one-step jog to the vendor sketch's exact ASCII byte."""
    try:
        return COMMAND_BYTES[(joint, direction)]
    except (KeyError, TypeError):
        raise ValueError("ADA031 joint or direction is unsupported") from None


def _command_byte_and_fields(command: dict) -> tuple[bytes, set[str], dict]:
    """Normalize the legacy jog schema and the connected-firmware v2 schema."""
    schema_version = command.get("schemaVersion")
    action = command.get("action")
    if schema_version == 1 and action == "ada031_control":
        command_byte = resolve_command_byte(command.get("joint"), command.get("direction"))
        return command_byte, LEGACY_COMMAND_FIELDS, {
            "action": "jog", "joint": command["joint"], "direction": command["direction"],
        }
    if schema_version != 2:
        raise ValueError("ADA031 command action or schema is unsupported")
    if action == "jog":
        command_byte = resolve_command_byte(command.get("joint"), command.get("direction"))
        return command_byte, COMMON_COMMAND_FIELDS | {"joint", "direction"}, {
            "action": action, "joint": command["joint"], "direction": command["direction"],
        }
    if action == "set_profile":
        profile = command.get("profile")
        try:
            command_byte = PROFILE_COMMAND_BYTES[profile]
        except (KeyError, TypeError):
            raise ValueError("ADA031 operation profile is unsupported") from None
        return command_byte, COMMON_COMMAND_FIELDS | {"profile"}, {"action": action, "profile": profile}
    if action in ACTION_COMMAND_BYTES:
        return ACTION_COMMAND_BYTES[action], COMMON_COMMAND_FIELDS, {"action": action}
    raise ValueError("ADA031 command action or schema is unsupported")


def validate_command(settings: Any, command: dict, assets: list[dict], retained: bool = False) -> tuple[dict, dict, bytes]:
    """Require a live, configured ADA031 profile and a gateway-local control allowlist."""
    if retained:
        raise ValueError("ADA031 motion commands must not be retained")
    if not isinstance(command, dict):
        raise ValueError("ADA031 command fields are invalid")
    command_byte, expected_fields, action_fields = _command_byte_and_fields(command)
    if set(command) != expected_fields:
        raise ValueError("ADA031 command fields are invalid")
    command_id = command.get("commandId")
    if not isinstance(command_id, str) or not SAFE_COMMAND_ID.fullmatch(command_id):
        raise ValueError("ADA031 command ID is invalid")
    asset_id = command.get("targetAssetId")
    allowed_assets = set(getattr(settings, "ada031_control_asset_ids", ()))
    if not isinstance(asset_id, str) or asset_id not in allowed_assets:
        raise ValueError("ADA031 asset is not enabled in ADA031_CONTROL_ASSET_IDS on this gateway")
    asset = next((item for item in assets if item.get("assetId") == asset_id), None)
    if not asset or asset.get("protocol") != "ada031_v4_serial":
        raise ValueError("Target asset has no ADA031 V4 serial profile")
    expires_at = command.get("expiresAt")
    now_ms = int(time.time() * 1000)
    if isinstance(expires_at, bool) or not isinstance(expires_at, int) or not now_ms < expires_at <= now_ms + 30_000 or expires_at > MAX_EPOCH_MILLISECONDS:
        raise ValueError("ADA031 command has expired or has an invalid expiry")
    return {
        "commandId": command_id,
        "targetAssetId": asset_id,
        "expiresAt": expires_at,
        **action_fields,
    }, asset, command_byte


def normalize_telemetry(record: dict) -> dict[str, float] | None:
    """Validate JSON emitted by AdeeptArmConnected.ino as numeric AAS signals."""
    if not isinstance(record, dict) or not ADA031_COUNTER_SIGNALS.intersection(record):
        # The firmware also emits an I2C discovery object during startup.
        return None
    if len(record) > len(ADA031_TELEMETRY_SIGNALS) or any(name not in ADA031_TELEMETRY_SIGNALS for name in record):
        raise ValueError("ADA031 telemetry contains unsupported fields")
    signals: dict[str, float] = {}
    for name, raw_value in record.items():
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or not math.isfinite(raw_value):
            raise ValueError(f"ADA031 telemetry signal {name} must be a finite number")
        value = float(raw_value)
        if name in ADA031_COUNTER_SIGNALS and (value < 0 or value > 4_294_967_295):
            raise ValueError(f"ADA031 counter {name} is outside the supported range")
        if name in ADA031_ENUM_SIGNALS:
            minimum, maximum = ADA031_ENUM_SIGNALS[name]
            if not value.is_integer() or not minimum <= value <= maximum:
                raise ValueError(f"ADA031 state signal {name} is outside the supported range")
        if name in ADA031_BOOLEAN_SIGNALS and value not in {0, 1}:
            raise ValueError(f"ADA031 boolean signal {name} must be zero or one")
        if name in ADA031_ANGLE_SIGNALS and not 0 <= value <= 180:
            raise ValueError(f"ADA031 angle signal {name} is outside the supported range")
        signals[name] = value
    return signals


class Ada031SerialCommandManager:
    """Reuse each controller port; opening USB serial can reset the arm to 90 degrees."""

    def __init__(self, serial_factory: Callable[..., Any] | None = None, sleeper: Callable[[float], None] = time.sleep, command_state=None):
        self._command_state = command_state
        self._serial_factory = serial_factory
        self._sleeper = sleeper
        self._ports: dict[str, tuple[str, Any]] = {}
        self._last_command_at: dict[str, float] = {}
        self._seen_commands: OrderedDict[str, float] = OrderedDict()
        self._lock = RLock()

    def _open_port(self, asset: dict):
        endpoint = str(asset.get("endpoint") or "")
        parsed = urlparse(endpoint)
        options = parse_qs(parsed.query)
        if parsed.scheme != "serial" or not parsed.path or options.get("baudrate", ["9600"])[0] != "9600":
            raise ValueError("ADA031 V4 endpoint must use USB serial at 9600 baud")
        if self._serial_factory is None:
            import serial
            factory = serial.Serial
        else:
            factory = self._serial_factory
        # Keep reads short so an operational stop request is not held behind a
        # one-second idle telemetry poll. This is not a safety-rated stop path.
        port = factory(parsed.path, baudrate=9600, timeout=0.25, write_timeout=1)
        self._sleeper(2.5)  # Allow the Arduino bootloader and the vendor 90-degree startup pose to finish.
        self._ports[asset["assetId"]] = (endpoint, port)
        return port

    def _discard_port(self, asset_id: str) -> None:
        existing = self._ports.pop(asset_id, None)
        if existing is not None:
            try:
                existing[1].close()
            except Exception:
                pass

    def execute(self, asset: dict, command: dict, command_byte: bytes) -> dict:
        with self._lock:
            asset_id = asset["assetId"]
            command_id = command["commandId"]
            now = time.monotonic()
            self._expire_seen(now)
            if command_id in self._seen_commands:
                return {"commandId": command_id, "targetAssetId": asset_id, "status": "duplicate_ignored"}
            last = self._last_command_at.get(asset_id)
            if command.get("action") != "stop_program" and last is not None and now - last < MIN_COMMAND_INTERVAL_SECONDS:
                raise ValueError("ADA031 command rate limit exceeded; wait before the next command")

            if int(command["expiresAt"]) <= int(time.time() * 1000):
                raise ValueError("ADA031 command expired before serial open")
            if self._command_state and not self._command_state.reserve_command(command_id, command["expiresAt"]):
                return {"commandId": command_id, "targetAssetId": asset_id, "status": "duplicate_ignored"}
            # Opening the controller can itself move it to the firmware startup pose.
            # Persist replay protection before opening as well as before writing.
            self._seen_commands[command_id] = now
            endpoint = str(asset.get("endpoint") or "")
            existing = self._ports.get(asset_id)
            if existing and existing[0] != endpoint:
                existing[1].close()
                del self._ports[asset_id]
            port = self._ports.get(asset_id, ("", None))[1] or self._open_port(asset)
            if int(command["expiresAt"]) <= int(time.time() * 1000):
                raise ValueError("ADA031 command expired before serial write")
            # Reserve before writing even without disk state, so an ambiguous write
            # or flush failure cannot trigger a blind second motion.
            self._seen_commands[command_id] = now
            try:
                written = port.write(command_byte)
                if written != 1:
                    raise RuntimeError("ADA031 serial controller did not accept the command byte")
                port.flush()
            except Exception:
                # Never retry a motion write whose delivery is ambiguous. Drop
                # the stale descriptor so the next distinct command or poll can
                # reopen the stable /dev/serial/by-id path after USB recovery.
                self._discard_port(asset_id)
                raise
            self._last_command_at[asset_id] = now
            self._seen_commands[command_id] = now
            while len(self._seen_commands) > 256:
                self._seen_commands.popitem(last=False)
            action = command.get("action", "jog")
            return {
                "commandId": command_id,
                "targetAssetId": asset_id,
                "action": action,
                **({"joint": command["joint"], "direction": command["direction"]} if action == "jog" and "joint" in command else {}),
                **({"profile": command["profile"]} if action == "set_profile" else {}),
                "status": "serial_write_accepted",
                "feedback": "controller_telemetry_pending",
            }

    def read_telemetry(self, asset: dict) -> dict[str, dict[str, float]]:
        """Read the newest complete JSON record without competing with command writes."""
        with self._lock:
            asset_id = asset["assetId"]
            endpoint = str(asset.get("endpoint") or "")
            existing = self._ports.get(asset_id)
            if existing and existing[0] != endpoint:
                existing[1].close()
                del self._ports[asset_id]
            port = self._ports.get(asset_id, ("", None))[1] or self._open_port(asset)
            newest: dict[str, float] | None = None
            try:
                for index in range(32):
                    if index > 0 and int(getattr(port, "in_waiting", 0)) <= 0:
                        break
                    raw = port.readline()
                    if not raw:
                        break
                    if len(raw) > MAX_SERIAL_RECORD_BYTES:
                        raise ValueError("ADA031 telemetry record exceeds the supported size")
                    try:
                        record = json.loads(raw.decode("utf-8", errors="strict").strip())
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    normalized = normalize_telemetry(record)
                    if normalized is not None:
                        newest = normalized
            except Exception:
                self._discard_port(asset_id)
                raise
            return {"assetSignals": newest} if newest is not None else {}

    def _expire_seen(self, now: float) -> None:
        while self._seen_commands:
            _command_id, created_at = next(iter(self._seen_commands.items()))
            if now - created_at <= 300:
                break
            self._seen_commands.popitem(last=False)

    def close_unused(self, active_asset_ids: set[str]) -> None:
        with self._lock:
            for asset_id in set(self._ports) - active_asset_ids:
                self._ports.pop(asset_id)[1].close()
                self._last_command_at.pop(asset_id, None)

    def close(self) -> None:
        with self._lock:
            for _endpoint, port in self._ports.values():
                port.close()
            self._ports.clear()
            self._last_command_at.clear()
