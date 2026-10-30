"""End-to-end: the demo timeline asserts the core invariants — a child
left alone alerts after grace and escalates when unanswered; a hot cabin
skips straight to escalation; Dog Mode pets, uncertain detections and
forgotten items never alert; an adult present clears."""
from tesla_cabin_sentinel.config import Settings, VehicleConfig
from tesla_cabin_sentinel.simulator import render_demo, run_demo


def _settings():
    return Settings(vehicles=[VehicleConfig("Model Y", "VINY")])


def test_demo_core_invariant_child_alerts_then_escalates():
    timeline = run_demo(_settings())
    child_scen = timeline[0]
    states = [r["state"] for r in child_scen["rows"]]
    assert states == ["WATCH", "WATCH", "ALERT", "ALERT", "ESCALATED", "CLEAR"]
    assert child_scen["alerts_sent"] == 3  # alert x2 + escalation


def test_demo_hot_cabin_escalates_immediately():
    timeline = run_demo(_settings())
    hot = timeline[1]
    assert hot["rows"][0]["state"] == "ESCALATED"
    assert hot["alerts_sent"] == 1


def test_demo_never_alerts_on_safe_scenarios():
    timeline = run_demo(_settings())
    for scen in timeline[2:]:
        assert scen["alerts_sent"] == 0, scen["title"]
        assert all(r["state"] in ("WATCH", "CLEAR") for r in scen["rows"])


def test_demo_renders_and_states_api_cost():
    text = render_demo(run_demo(_settings()))
    assert "CABIN SENTINEL" in text
    assert "$0.00" in text
    assert "ESCALATED" in text
