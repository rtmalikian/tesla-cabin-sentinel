"""Pure cabin-occupancy decision logic — no network, `now` injected, fully
unit-testable. This is the brain that runs the day Tesla ships a cabin
camera / rear-occupant endpoint (see API_PROPOSAL.md); until then the
simulator feeds it synthetic frames and the chat endpoint accepts
frame descriptions in plain words.

States (the alert ladder):
  CLEAR      — nobody vulnerable alone in the car; nothing to do.
  WATCH      — something worth logging but not alerting on (low-confidence
               detection, a forgotten item, a pet with Dog Mode keeping the
               cabin safe, an occupant with an adult present).
  ALERT      — a child or pet is alone in a locked, parked car past the
               configured grace period: notify the owner now.
  ESCALATED  — the alert went unacknowledged past the escalation delay, or
               the cabin is already dangerously hot: louder wording, second
               contact, and (once the API exists) horn + hazard flash.

Safety bias: when in doubt, escalate toward the human, never away. A
low-confidence frame never alerts on its own, but it also never clears
an already-running alert — only a confident "nobody there" frame, an
adult present, or an explicit acknowledgement ends one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

OCCUPANT_TYPES = ("child", "pet", "adult", "item", "none")
ITEM_KINDS = ("bag", "phone", "laptop", "keys", "stroller", "other")


@dataclass
class CabinFrame:
    """One cabin observation, as the future API would report it."""
    vehicle: str
    occupant: str = "none"          # child | pet | adult | item | none
    confidence: int = 100           # 0-100 detector confidence
    item_kind: str = ""             # when occupant == "item"
    parked: bool = True
    locked: bool = True
    driving: bool = False
    cabin_temp_f: float | None = None
    climate_on: bool = False        # Dog Mode / Keep Climate On
    adult_present: bool = False
    timestamp: datetime | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.occupant not in OCCUPANT_TYPES:
            raise ValueError(f"occupant must be one of {OCCUPANT_TYPES}, "
                             f"got {self.occupant!r}")
        if not (0 <= self.confidence <= 100):
            raise ValueError(f"confidence must be 0-100, got {self.confidence}")


@dataclass
class Detection:
    state: str                      # CLEAR | WATCH | ALERT | ESCALATED
    summary: str                    # one plain-English sentence
    reasons: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    # Minutes the vulnerable occupant has been alone (0 when not alone).
    alone_minutes: float = 0.0
    # True when this detection should notify a human right now.
    notify: bool = False


def _describe(frame: CabinFrame) -> str:
    if frame.occupant == "item":
        kind = frame.item_kind or "item"
        return f"a forgotten {kind}"
    if frame.occupant == "none":
        return "nobody"
    return f"a {frame.occupant}"


def evaluate(frame: CabinFrame, settings, alone_since: datetime | None,
             alerted_at: datetime | None) -> Detection:
    """Evaluate one frame given the episode state so far.

    alone_since: when the current alone-episode started (None if nobody
        vulnerable is currently alone). alerted_at: when the current
        alert first fired (None if it hasn't).
    """
    now = frame.timestamp
    desc = _describe(frame)
    alone_minutes = ((now - alone_since).total_seconds() / 60.0
                     if alone_since else 0.0)

    # The car is moving, or an adult is with them: nobody is "left behind".
    if frame.driving or frame.adult_present:
        return Detection("CLEAR",
                         f"{desc.capitalize()} in the {frame.vehicle} with "
                         f"an adult present — nothing to do."
                         if frame.adult_present
                         else f"The {frame.vehicle} is driving — "
                         f"occupancy checks only apply while parked.",
                         reasons=["car is driving" if frame.driving
                                  else "adult present"],
                         alone_minutes=0.0)
    if not frame.parked:
        return Detection("CLEAR", f"The {frame.vehicle} is not parked.",
                         reasons=["not parked"])

    # Nobody there: the episode (if any) is over.
    if frame.occupant == "none":
        return Detection("CLEAR",
                         f"Nobody detected in the {frame.vehicle}.",
                         reasons=["cabin empty"], alone_minutes=0.0)

    # A forgotten item is a reminder, never an emergency.
    if frame.occupant == "item":
        return Detection(
            "WATCH",
            f"You left {desc} in the {frame.vehicle} — worth a reminder, "
            f"not an alarm.",
            reasons=["forgotten item", "no vulnerable occupant"],
            actions=[f"send_reminder: {desc} left in {frame.vehicle}"])

    # Low confidence: log it, watch it, never alert on it alone.
    if frame.confidence < settings.confidence_threshold:
        return Detection(
            "WATCH",
            f"Possible {frame.occupant} in the {frame.vehicle}, but the "
            f"detector is only {frame.confidence}% sure (threshold "
            f"{settings.confidence_threshold}%) — watching, not alerting.",
            reasons=[f"confidence {frame.confidence}% below threshold "
                     f"{settings.confidence_threshold}%"],
            actions=["log_watch"])

    # An adult alone in a parked car is not a sentinel event.
    if frame.occupant == "adult":
        return Detection("CLEAR",
                         f"An adult is sitting in the parked {frame.vehicle}.",
                         reasons=["adult occupant only"])

    # --- Child or pet, confidently detected, parked -------------------
    # Dog Mode / climate keeping the cabin safe: a pet is watched, not
    # alerted on — but a child is ALWAYS an alert, climate or not.
    if (frame.occupant == "pet" and frame.climate_on
            and frame.cabin_temp_f is not None
            and frame.cabin_temp_f <= settings.climate_safe_max_f):
        return Detection(
            "WATCH",
            f"Your pet is in the {frame.vehicle} with the climate on and "
            f"the cabin at {frame.cabin_temp_f:.0f}°F — comfortable, so "
            f"this is a watch, not an alert.",
            reasons=["pet with climate on", "cabin temperature safe"],
            actions=["log_watch"], alone_minutes=alone_minutes)

    # Unlocked car: the occupant can (in principle) get out, but a small
    # child still can't be assumed safe — alert, but say so plainly.
    if not frame.locked:
        return Detection(
            "ALERT",
            f"A {frame.occupant} is alone in the {frame.vehicle} and the "
            f"car is NOT locked — check on them now.",
            reasons=["vulnerable occupant alone", "car unlocked"],
            actions=["notify_owner"],
            alone_minutes=alone_minutes, notify=True)

    # Dangerous heat skips the whole ladder.
    if (frame.cabin_temp_f is not None
            and frame.cabin_temp_f >= settings.danger_temp_f):
        return Detection(
            "ESCALATED",
            f"URGENT: a {frame.occupant} is alone in the {frame.vehicle} "
            f"and the cabin is already {frame.cabin_temp_f:.0f}°F — go to "
            f"the car NOW.",
            reasons=["vulnerable occupant alone",
                     f"cabin {frame.cabin_temp_f:.0f}°F at/above danger "
                     f"threshold {settings.danger_temp_f}°F"],
            actions=["notify_owner", "escalate", "horn_and_hazards"],
            alone_minutes=alone_minutes, notify=True)

    # Grace period: still inside it → watch, with the countdown stated.
    # (A first sighting counts as 0 minutes alone, so it starts the
    # grace period rather than skipping it.)
    if alone_minutes < settings.alert_after_minutes:
        remaining = settings.alert_after_minutes - alone_minutes
        return Detection(
            "WATCH",
            f"A {frame.occupant} has been alone in the locked "
            f"{frame.vehicle} for {alone_minutes:.0f} minute(s) — alert "
            f"fires in {remaining:.0f} more minute(s) if nobody returns.",
            reasons=["vulnerable occupant alone", "inside grace period"],
            actions=["log_watch"], alone_minutes=alone_minutes)

    # Past grace period: alert. Past escalation delay unacknowledged: escalate.
    if (alerted_at is not None
            and (now - alerted_at).total_seconds() / 60.0
            >= settings.escalate_after_minutes):
        waited = (now - alerted_at).total_seconds() / 60.0
        return Detection(
            "ESCALATED",
            f"ESCALATED: a {frame.occupant} has been alone in the "
            f"{frame.vehicle} for {alone_minutes:.0f} minute(s) and the "
            f"alert {waited:.0f} minute(s) ago went unanswered — alerting "
            f"your second contact now.",
            reasons=["vulnerable occupant alone", "alert unacknowledged"],
            actions=["notify_owner", "escalate", "notify_second_contact"],
            alone_minutes=alone_minutes, notify=True)

    return Detection(
        "ALERT",
        f"A {frame.occupant} has been alone in the locked {frame.vehicle} "
        f"for {alone_minutes:.0f} minute(s) — alerting you now.",
        reasons=["vulnerable occupant alone", "grace period passed"],
        actions=["notify_owner"],
        alone_minutes=alone_minutes, notify=True)


def next_episode_state(frame: CabinFrame, settings, alone_since: datetime | None,
                       alerted_at: datetime | None):
    """Advance (alone_since, alerted_at) given a new frame.

    Returns (detection, new_alone_since, new_alerted_at). A confident
    vulnerable-occupant frame starts/continues an episode; a confident
    empty/adult frame ends it. Low-confidence frames never start or end
    an episode on their own.
    """
    now = frame.timestamp
    vulnerable = frame.occupant in ("child", "pet")
    confident = frame.confidence >= settings.confidence_threshold
    episode_active = (vulnerable and confident and frame.parked
                      and not frame.driving and not frame.adult_present)
    # Safety bias: an uncertain "empty" (or "adult") reading must never
    # close an open episode — only a confident one does.
    if alone_since is not None and not confident \
            and frame.occupant in ("none", "adult"):
        return (Detection(
            "WATCH",
            f"Uncertain reading ({frame.confidence}% sure the cabin is "
            f"empty) — keeping the current episode open until a confident "
            f"check.",
            reasons=["low-confidence empty reading", "episode kept open"],
            actions=["log_watch"], alone_minutes=(
                (now - alone_since).total_seconds() / 60.0)),
            alone_since, alerted_at)
    detection = evaluate(frame, settings, alone_since, alerted_at)
    if episode_active:
        new_alone = alone_since or now
        new_alerted = alerted_at
        if detection.state in ("ALERT", "ESCALATED") and alerted_at is None:
            new_alerted = now
        return detection, new_alone, new_alerted
    if frame.occupant == "none" and confident:
        return detection, None, None
    if frame.occupant == "adult" and confident:
        return detection, None, None
    # Watch frames (items, low confidence): episode state unchanged.
    return detection, alone_since, alerted_at
