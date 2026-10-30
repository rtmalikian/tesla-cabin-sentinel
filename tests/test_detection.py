"""Decision-logic unit tests, including edge cases. `now` is injected via
frame timestamps; no network, no clock dependence."""
from datetime import datetime, timedelta

import pytest

from tesla_cabin_sentinel.config import Settings
from tesla_cabin_sentinel.detection import (
    CabinFrame, evaluate, next_episode_state)

T0 = datetime(2026, 10, 30, 13, 0, 0)


def _settings(**overrides):
    s = Settings()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _frame(**overrides):
    base = dict(vehicle="Model Y", occupant="child", confidence=95,
                parked=True, locked=True, timestamp=T0)
    base.update(overrides)
    return CabinFrame(**base)


def _run(frames, settings):
    """Feed frames through the episode machine; return detections."""
    alone = alerted = None
    out = []
    for fr in frames:
        d, alone, alerted = next_episode_state(fr, settings, alone, alerted)
        out.append(d)
    return out


def test_empty_cabin_is_clear():
    s = _settings()
    d = evaluate(_frame(occupant="none"), s, None, None)
    assert d.state == "CLEAR" and not d.notify


def test_adult_alone_is_clear_and_adult_present_clears_episode():
    s = _settings()
    assert evaluate(_frame(occupant="adult"), s, None, None).state == "CLEAR"
    ds = _run([_frame(timestamp=T0),
               _frame(timestamp=T0 + timedelta(minutes=5),
                      adult_present=True)], s)
    assert ds[1].state == "CLEAR"


def test_driving_is_clear_even_with_child():
    s = _settings()
    d = evaluate(_frame(driving=True, parked=False), s, None, None)
    assert d.state == "CLEAR"


def test_grace_period_then_alert_then_escalation():
    s = _settings(alert_after_minutes=2, escalate_after_minutes=5)
    ds = _run([
        _frame(timestamp=T0),
        _frame(timestamp=T0 + timedelta(minutes=1)),
        _frame(timestamp=T0 + timedelta(minutes=2)),
        _frame(timestamp=T0 + timedelta(minutes=4)),
        _frame(timestamp=T0 + timedelta(minutes=7)),
    ], s)
    assert [d.state for d in ds] == ["WATCH", "WATCH", "ALERT", "ALERT",
                                     "ESCALATED"]
    assert ds[2].notify and ds[4].notify and not ds[0].notify


def test_zero_grace_alerts_immediately():
    s = _settings(alert_after_minutes=0)
    ds = _run([_frame(timestamp=T0)], s)
    assert ds[0].state == "ALERT"


def test_danger_temp_skips_straight_to_escalation():
    s = _settings(danger_temp_f=95)
    d = evaluate(_frame(cabin_temp_f=102), s, None, None)
    assert d.state == "ESCALATED" and d.notify
    assert "horn_and_hazards" in d.actions


def test_pet_with_dog_mode_and_safe_temp_is_watch_not_alert():
    s = _settings()
    ds = _run([
        _frame(timestamp=T0, occupant="pet", climate_on=True,
               cabin_temp_f=72),
        _frame(timestamp=T0 + timedelta(minutes=30), occupant="pet",
               climate_on=True, cabin_temp_f=73),
    ], s)
    assert all(d.state == "WATCH" for d in ds)
    assert not any(d.notify for d in ds)


def test_pet_with_dog_mode_but_hot_cabin_still_alerts():
    s = _settings()
    d = evaluate(_frame(occupant="pet", climate_on=True, cabin_temp_f=90),
                 s, T0 - timedelta(minutes=10), None)
    assert d.state == "ALERT"


def test_child_with_climate_on_still_alerts():
    # Climate never excuses a child alone — only pets get the Dog Mode pass.
    s = _settings()
    d = evaluate(_frame(occupant="child", climate_on=True, cabin_temp_f=72),
                 s, T0 - timedelta(minutes=10), None)
    assert d.state == "ALERT"


def test_low_confidence_never_alerts_and_never_starts_episode():
    s = _settings(confidence_threshold=70)
    ds = _run([
        _frame(timestamp=T0, confidence=55),
        _frame(timestamp=T0 + timedelta(minutes=60), confidence=58),
    ], s)
    assert all(d.state == "WATCH" for d in ds)
    assert not any(d.notify for d in ds)


def test_confidence_exactly_at_threshold_counts():
    s = _settings(confidence_threshold=70, alert_after_minutes=0)
    d = evaluate(_frame(confidence=70), s, T0, None)
    assert d.state == "ALERT"


def test_forgotten_item_is_reminder_not_alarm():
    s = _settings()
    d = evaluate(_frame(occupant="item", item_kind="bag"), s, None, None)
    assert d.state == "WATCH" and not d.notify
    assert any("reminder" in a for a in d.actions)


def test_unlocked_car_alerts_immediately():
    s = _settings()
    d = evaluate(_frame(locked=False), s, T0, None)
    assert d.state == "ALERT" and d.notify


def test_empty_frame_ends_episode_and_resets_alert():
    s = _settings(alert_after_minutes=0)
    ds = _run([
        _frame(timestamp=T0),
        _frame(timestamp=T0 + timedelta(minutes=1), occupant="none",
               confidence=99),
        _frame(timestamp=T0 + timedelta(minutes=2)),
    ], s)
    # After the confident empty frame, a fresh child frame alerts again
    # immediately (zero grace period).
    assert [d.state for d in ds] == ["ALERT", "CLEAR", "ALERT"]


def test_low_confidence_frame_does_not_end_an_active_episode():
    s = _settings(alert_after_minutes=0)
    ds = _run([
        _frame(timestamp=T0),
        _frame(timestamp=T0 + timedelta(minutes=1), occupant="none",
               confidence=40),  # unsure the cabin is empty
        _frame(timestamp=T0 + timedelta(minutes=2)),
    ], s)
    # The uncertain "empty" frame must not clear the alert.
    assert ds[1].state == "WATCH"
    assert ds[2].state == "ALERT"


def test_bad_frame_values_rejected():
    with pytest.raises(ValueError):
        CabinFrame(vehicle="Model Y", occupant="alien")
    with pytest.raises(ValueError):
        CabinFrame(vehicle="Model Y", confidence=101)
