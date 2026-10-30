"""Configuration for Tesla Cabin Sentinel. All settings come from the
environment (see .env.example). Run `tcsentinel setup` and answer a few
plain-language questions — it writes .env for you. .env is git-ignored so
secrets never leave your machine.

IMPORTANT: Tesla's Fleet API exposes no cabin camera or rear-occupant
sensor today, so Cabin Sentinel is a FUTURE-API product: the detection
brain, the AI endpoint, the alert ladder and the simulator are all real,
but live car checks run against the simulator until Tesla ships the
endpoints proposed in API_PROPOSAL.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(Exception):
    pass


@dataclass
class VehicleConfig:
    name: str
    vin: str = ""   # may be blank: nickname-only cars get a VIN at pairing time


@dataclass
class Settings:
    client_id: str = ""
    client_secret: str = ""
    region: str = "na"
    redirect_uri: str = "http://localhost:8080/callback"
    token_file: str = "~/.tcs/tokens.json"
    vehicles: list[VehicleConfig] = field(default_factory=list)
    # The OpenAI-compatible server this app exposes.
    server_host: str = "127.0.0.1"
    server_port: int = 8645
    server_api_key: str = ""
    model_id: str = "tesla-cabin-sentinel"
    # Pluggable LLM backend (any OpenAI-compatible API; default: local Ollama).
    ai_base_url: str = "http://localhost:11434/v1"
    ai_api_key: str = ""
    ai_model: str = "llama3.1"
    ai_mode: str = "auto"             # auto | always | never
    ai_timeout_seconds: float = 20.0
    embedding_dim: int = 384
    dry_run: bool = False
    data_dir: str = "~/.tcs"
    # ---- Cabin Sentinel settings --------------------------------------
    # Where alerts go: an ntfy.sh topic (e.g. "my-family-alerts") or a
    # full webhook URL. Blank = alerts are printed/logged only.
    alert_destination: str = ""
    # Minutes a child/pet may sit alone in a locked, parked car before the
    # first alert fires. (Parents set this; the default is deliberately
    # short — a parked car heats fast.)
    alert_after_minutes: int = 2
    # Minutes after the first alert with no acknowledgement before the
    # alert escalates (louder channel, second contact, emergency wording).
    escalate_after_minutes: int = 5
    # How often the (future) cabin check runs while parked, in minutes.
    check_interval_minutes: int = 1
    # Minimum detector confidence (0-100) treated as a real occupant.
    # Below this, the frame is a "watch" — logged, never alerted on.
    confidence_threshold: int = 70
    # Cabin temperature (°F) above which an alert escalates immediately,
    # without waiting out the escalation delay.
    danger_temp_f: int = 95
    # Dog Mode / climate running keeps a pet safe: with climate on and the
    # cabin at a safe temperature, a pet alone is a watch, not an alert.
    climate_safe_max_f: int = 85


def _parse_vehicles(raw: str) -> list[VehicleConfig]:
    """Format: name=VIN,name2=VIN2, or bare nicknames (VIN filled in later)."""
    vehicles = []
    for idx, item in enumerate(raw.split(",")):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            name, vin = item.split("=", 1)
            vehicles.append(VehicleConfig(name=name.strip() or f"car-{idx + 1}",
                                          vin=vin.strip()))
        else:
            vehicles.append(VehicleConfig(name=item, vin=""))
    if not vehicles:
        raise ConfigError("TCS_VEHICLES is empty — add at least one car nickname")
    return vehicles


def _int(env: dict, key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{key} must be a whole number, got {raw!r}") from exc


def _float(env: dict, key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _bool(env: dict, key: str, default: bool = False) -> bool:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_settings(env: dict | None = None) -> Settings:
    env = os.environ if env is None else env
    s = Settings()
    s.client_id = env.get("TESLA_CLIENT_ID", "")
    s.client_secret = env.get("TESLA_CLIENT_SECRET", "")
    s.region = env.get("TESLA_REGION", "na").strip().lower()
    if s.region not in ("na", "eu", "cn"):
        raise ConfigError(f"TESLA_REGION must be na|eu|cn, got {s.region!r}")
    s.redirect_uri = env.get("TESLA_REDIRECT_URI", s.redirect_uri)
    s.token_file = env.get("TCS_TOKEN_FILE", s.token_file)
    raw_vehicles = env.get("TCS_VEHICLES", "")
    if raw_vehicles.strip():
        s.vehicles = _parse_vehicles(raw_vehicles)
    s.server_host = env.get("TCS_SERVER_HOST", s.server_host)
    s.server_port = _int(env, "TCS_SERVER_PORT", s.server_port)
    s.server_api_key = env.get("TCS_SERVER_API_KEY", "")
    s.model_id = env.get("TCS_MODEL_ID", s.model_id)
    s.ai_base_url = env.get("TCS_AI_BASE_URL", s.ai_base_url).rstrip("/")
    s.ai_api_key = env.get("TCS_AI_API_KEY", "")
    s.ai_model = env.get("TCS_AI_MODEL", s.ai_model)
    s.ai_mode = env.get("TCS_AI_MODE", s.ai_mode).strip().lower()
    if s.ai_mode not in ("auto", "always", "never"):
        raise ConfigError(f"TCS_AI_MODE must be auto|always|never, got {s.ai_mode!r}")
    s.ai_timeout_seconds = _float(env, "TCS_AI_TIMEOUT_SECONDS", s.ai_timeout_seconds)
    s.embedding_dim = _int(env, "TCS_EMBEDDING_DIM", s.embedding_dim)
    if not (8 <= s.embedding_dim <= 4096):
        raise ConfigError("TCS_EMBEDDING_DIM must be between 8 and 4096")
    s.dry_run = _bool(env, "TCS_DRY_RUN")
    s.data_dir = env.get("TCS_DATA_DIR", s.data_dir)
    s.alert_destination = env.get("TCS_ALERT_DESTINATION", "").strip()
    s.alert_after_minutes = _int(env, "TCS_ALERT_AFTER_MINUTES",
                                 s.alert_after_minutes)
    if not (0 <= s.alert_after_minutes <= 30):
        raise ConfigError(
            f"TCS_ALERT_AFTER_MINUTES must be 0 to 30, got "
            f"{s.alert_after_minutes}. A short delay is safest — re-run "
            f"`tcsentinel setup` and pick 0 to 5 minutes.")
    s.escalate_after_minutes = _int(env, "TCS_ESCALATE_AFTER_MINUTES",
                                    s.escalate_after_minutes)
    if not (1 <= s.escalate_after_minutes <= 60):
        raise ConfigError(
            f"TCS_ESCALATE_AFTER_MINUTES must be 1 to 60, got "
            f"{s.escalate_after_minutes}")
    s.check_interval_minutes = _int(env, "TCS_CHECK_INTERVAL_MINUTES",
                                    s.check_interval_minutes)
    if not (1 <= s.check_interval_minutes <= 15):
        raise ConfigError(
            f"TCS_CHECK_INTERVAL_MINUTES must be 1 to 15, got "
            f"{s.check_interval_minutes}")
    s.confidence_threshold = _int(env, "TCS_CONFIDENCE_THRESHOLD",
                                  s.confidence_threshold)
    if not (50 <= s.confidence_threshold <= 99):
        raise ConfigError(
            f"TCS_CONFIDENCE_THRESHOLD must be 50 to 99, got "
            f"{s.confidence_threshold}")
    s.danger_temp_f = _int(env, "TCS_DANGER_TEMP_F", s.danger_temp_f)
    if not (80 <= s.danger_temp_f <= 120):
        raise ConfigError(f"TCS_DANGER_TEMP_F must be 80 to 120, got {s.danger_temp_f}")
    s.climate_safe_max_f = _int(env, "TCS_CLIMATE_SAFE_MAX_F",
                                s.climate_safe_max_f)
    if not (60 <= s.climate_safe_max_f <= 95):
        raise ConfigError(
            f"TCS_CLIMATE_SAFE_MAX_F must be 60 to 95, got {s.climate_safe_max_f}")
    return s
