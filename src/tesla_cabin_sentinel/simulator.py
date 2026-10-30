"""Fake fleet + synthetic cabin events over virtual time. No API calls,
no real cars, no credentials, no network.

The demo proves the core invariants:
  - a child left alone in a locked car alerts after the grace period and
    escalates when unanswered;
  - a dangerously hot cabin skips straight to escalation;
  - a pet with Dog Mode on and a safe cabin temperature is a watch, not
    an alert;
  - a low-confidence detection never alerts on its own;
  - a forgotten bag is a reminder, never an alarm;
  - a child with an adult present, or an empty cabin, clears the episode.

Estimated Fleet API cost of the simulation itself: $0.00 — it makes no
live calls. When the proposed API lands, a parked car checked once a
minute with no wakes costs roughly the data-call rate only (see README).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .detection import CabinFrame
from .service import CabinSentinelService


def _frame(vehicle: str, when: datetime, **kwargs) -> CabinFrame:
    kwargs.setdefault("parked", True)
    kwargs.setdefault("locked", True)
    kwargs.setdefault("timestamp", when)
    return CabinFrame(vehicle=vehicle, **kwargs)


def build_scenarios(settings):
    """Returns a list of (title, [frames]) scenarios over virtual time."""
    base = datetime(2026, 10, 30, 13, 0, 0)
    t = lambda m: base + timedelta(minutes=m)  # noqa: E731
    car = settings.vehicles[0].name if settings.vehicles else "Model Y"
    scenarios = []

    # 1. The core invariant: child left, alert, then escalation.
    scenarios.append(("Child left behind — alert, then escalation", [
        _frame(car, t(0), occupant="child", confidence=96),
        _frame(car, t(1), occupant="child", confidence=97),
        _frame(car, t(2), occupant="child", confidence=97),   # grace passed
        _frame(car, t(4), occupant="child", confidence=98),
        _frame(car, t(7), occupant="child", confidence=98),   # escalated
        _frame(car, t(8), occupant="none", confidence=99),    # rescued
    ]))
    # 2. Dangerous heat skips the ladder.
    scenarios.append(("Hot cabin — straight to escalation", [
        _frame(car, t(10), occupant="child", confidence=95,
               cabin_temp_f=102),
    ]))
    # 3. Dog Mode keeps a pet safe.
    scenarios.append(("Pet with Dog Mode on — watch, not alert", [
        _frame(car, t(12), occupant="pet", confidence=94, climate_on=True,
               cabin_temp_f=72),
        _frame(car, t(20), occupant="pet", confidence=94, climate_on=True,
               cabin_temp_f=73),
        _frame(car, t(21), occupant="none", confidence=99),
    ]))
    # 4. Low confidence never alerts.
    scenarios.append(("Uncertain detection — watch only", [
        _frame(car, t(22), occupant="child", confidence=55),
        _frame(car, t(30), occupant="child", confidence=58),
    ]))
    # 5. Forgotten item = reminder.
    scenarios.append(("Forgotten bag — reminder, not alarm", [
        _frame(car, t(32), occupant="item", item_kind="bag",
               confidence=92),
    ]))
    # 6. Adult present / empty cabin clears.
    scenarios.append(("Child with an adult — all clear", [
        _frame(car, t(34), occupant="child", confidence=96,
               adult_present=True),
        _frame(car, t(35), occupant="none", confidence=99),
    ]))
    return scenarios


def run_demo(settings):
    """Runs every scenario through a fresh service; returns the timeline."""
    timeline = []
    original_dry_run = settings.dry_run
    for title, frames in build_scenarios(settings):
        service = CabinSentinelService(settings, alert_sink=lambda m: None)
        # The demo shows real alert delivery; a user's dry-run preference
        # is restored afterwards and never changed on disk.
        service.settings.dry_run = False
        rows = []
        for fr in frames:
            outcome = service.check_frame(fr)
            d = outcome["detection"]
            rows.append({
                "time": fr.timestamp.strftime("%I:%M %p"),
                "frame": _frame_text(fr),
                "state": d.state,
                "summary": d.summary,
                "alert": outcome["status"],
            })
        timeline.append({"title": title, "rows": rows,
                         "alerts_sent": len(service.sent_alerts)})
    settings.dry_run = original_dry_run
    return timeline


def _frame_text(fr: CabinFrame) -> str:
    if fr.occupant == "item":
        who = f"forgotten {fr.item_kind or 'item'}"
    elif fr.occupant == "none":
        who = "cabin empty"
    else:
        who = f"{fr.occupant} ({fr.confidence}% sure)"
    bits = [who]
    if fr.cabin_temp_f is not None:
        bits.append(f"cabin {fr.cabin_temp_f:.0f}°F")
    if fr.climate_on:
        bits.append("climate on")
    if fr.adult_present:
        bits.append("adult present")
    if not fr.locked:
        bits.append("UNLOCKED")
    return ", ".join(bits)


def render_demo(timeline) -> str:
    lines = []
    lines.append("CABIN SENTINEL — SIMULATED DEMO  (pretend cars, pretend "
                 "cabin frames; no real car is involved)")
    lines.append("")
    total_alerts = 0
    for scen in timeline:
        lines.append(f"== {scen['title']} ==")
        for row in scen["rows"]:
            lines.append(f"  {row['time']}  [{row['state']:<9}] {row['frame']}")
            lines.append(f"           → {row['summary']}")
            if row["alert"] not in ("logged",):
                lines.append(f"           alert: {row['alert']}")
        lines.append(f"  alerts sent in this scenario: {scen['alerts_sent']}")
        total_alerts += scen["alerts_sent"]
        lines.append("")
    lines.append(f"Total alerts sent across all scenarios: {total_alerts}")
    lines.append("Estimated Fleet API cost of this simulation: $0.00 "
                 "(no live calls; all frames are synthetic).")
    lines.append("When Tesla ships the proposed cabin endpoints, a parked car")
    lines.append("checked once a minute costs only data calls — no wakes, "
                 "no commands — while parked.")
    return "\n".join(lines)
