import pytest

from tesla_cabin_sentinel.config import ConfigError, load_settings

BASE = {"TCS_VEHICLES": "Model Y=VINY"}


def _load(**overrides):
    env = dict(BASE)
    env.update(overrides)
    return load_settings(env)


def test_defaults_are_safety_first():
    s = _load()
    assert s.alert_after_minutes == 2
    assert s.escalate_after_minutes == 5
    assert s.check_interval_minutes == 1
    assert s.confidence_threshold == 70
    assert s.danger_temp_f == 95
    assert s.climate_safe_max_f == 85
    assert s.ai_base_url == "http://localhost:11434/v1"
    assert s.model_id == "tesla-cabin-sentinel"
    assert s.server_port == 8645
    assert s.vehicles[0].name == "Model Y"


def test_env_overrides():
    s = _load(TCS_ALERT_AFTER_MINUTES="0", TCS_DANGER_TEMP_F="100",
              TCS_ALERT_DESTINATION="ntfy://family-car-alerts",
              TCS_AI_MODE="never")
    assert s.alert_after_minutes == 0
    assert s.danger_temp_f == 100
    assert s.alert_destination == "ntfy://family-car-alerts"
    assert s.ai_mode == "never"


def test_bad_values_rejected_with_plain_language():
    with pytest.raises(ConfigError, match="0 to 30"):
        _load(TCS_ALERT_AFTER_MINUTES="45")
    with pytest.raises(ConfigError, match="1 to 60"):
        _load(TCS_ESCALATE_AFTER_MINUTES="0")
    with pytest.raises(ConfigError, match="50 to 99"):
        _load(TCS_CONFIDENCE_THRESHOLD="10")
    with pytest.raises(ConfigError, match="80 to 120"):
        _load(TCS_DANGER_TEMP_F="70")
    with pytest.raises(ConfigError, match="auto|always|never"):
        _load(TCS_AI_MODE="sometimes")
    with pytest.raises(ConfigError, match="na|eu|cn"):
        _load(TESLA_REGION="xx")


def test_vehicles_parse_and_empty_rejected():
    s = _load(TCS_VEHICLES="Model Y,Model 3=VIN3")
    assert [v.name for v in s.vehicles] == ["Model Y", "Model 3"]
    assert s.vehicles[0].vin == "" and s.vehicles[1].vin == "VIN3"
    with pytest.raises(ConfigError, match="empty"):
        _load(TCS_VEHICLES=" , ")


def test_booleans():
    s = _load(TCS_DRY_RUN="yes")
    assert s.dry_run is True
    s = _load(TCS_DRY_RUN="0")
    assert s.dry_run is False
