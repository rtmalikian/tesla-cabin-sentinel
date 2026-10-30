"""Transport-independent Cabin Sentinel service: takes OpenAI-shaped
request dicts, returns OpenAI-shaped response dicts. The HTTP server
(server.py) is a thin wrapper; tests drive this class directly.

Flow for a user message:
  1. A frame description ("child alone in the Model Y, 98 degrees") →
     the deterministic detection engine evaluates it and, if it is an
     alert, notifies through the configured alert sink.
  2. "acknowledge" → ends the current alert for that car.
  3. Anything else → the LLM backend (if configured) answers with the
     sentinel settings + latest assessment as context; an allowlisted
     JSON command block is validated and executed. With no backend, the
     capability blurb answers instead of an error.

Privacy: assessments live on this machine only. Vehicle data goes ONLY
to the user-configured LLM backend, nowhere else. And the honesty note
that matters most: Tesla exposes no cabin camera today, so a "check"
against a real car is impossible until the proposed API lands — the
service says so instead of pretending.
"""
from __future__ import annotations

import itertools
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from .detection import CabinFrame, next_episode_state
from .embeddings import embed_text
from .llm import LlmBackend, PROPOSED_COMMANDS, extract_command

CAPABILITY_BLURB = (
    "I watch for children and pets left alone in a parked Tesla and alert "
    "you — first alert after a short grace period, escalation if it goes "
    "unanswered or the cabin gets dangerously hot. Tell me what a cabin "
    "check sees (for example: \"child alone in the Model Y, cabin 98°F\") "
    "and I'll assess it. One honest limit: Tesla's Fleet API has no "
    "cabin camera or rear-occupant sensor today, so live checks against a "
    "real car are a proposed feature (see API_PROPOSAL.md) — the brain, "
    "the alerts and the simulator are real now, and the car check plugs "
    "in the day the API lands."
)

_CHECK_HINTS = ("left", "alone", "anyone in", "check", "cabin", "in the car",
                "forgot", "still in")
_ACK_HINTS = ("acknowledge", "i'm on it", "i got it", "handled", "on my way")

_TEMP_RE = re.compile(r"(\d{2,3})\s*(?:°|degrees?|f\b)", re.IGNORECASE)
_CONF_RE = re.compile(r"(\d{1,3})\s*%\s*(?:sure|confident|confidence)",
                      re.IGNORECASE)
_ITEM_WORDS = {"bag": "bag", "phone": "phone", "laptop": "laptop",
               "keys": "keys", "stroller": "stroller", "backpack": "bag"}


def parse_frame(text: str, settings, vehicle_name: str = "") -> CabinFrame:
    """Best-effort read of a cabin frame from a plain-language message."""
    low = text.lower()
    occupant, item_kind = "none", ""
    if any(w in low for w in ("child", "kid", "baby", "toddler", "infant")):
        occupant = "child"
    elif any(w in low for w in ("pet", "dog", "cat", "puppy")):
        occupant = "pet"
    elif any(w in low for w in ("adult", "grown-up", "grownup")):
        occupant = "adult"
    else:
        for word, kind in _ITEM_WORDS.items():
            if word in low:
                occupant, item_kind = "item", kind
                break
    conf_m = _CONF_RE.search(text)
    confidence = int(conf_m.group(1)) if conf_m else 100
    temp_m = _TEMP_RE.search(text)
    temp = float(temp_m.group(1)) if temp_m else None
    return CabinFrame(
        vehicle=vehicle_name,
        occupant=occupant,
        confidence=max(0, min(100, confidence)),
        item_kind=item_kind,
        parked="driving" not in low,
        locked="unlocked" not in low,
        driving="driving" in low,
        cabin_temp_f=temp,
        climate_on=("dog mode" in low or "climate on" in low
                    or "keep climate" in low),
        adult_present=("with an adult" in low or "adult with" in low
                       or "adult present" in low),
    )


@dataclass
class Episode:
    alone_since: datetime | None = None
    alerted_at: datetime | None = None
    acknowledged: bool = False
    last_detection: object = None
    history: list = field(default_factory=list)


class CabinSentinelService:
    def __init__(self, settings, client_factory=None, llm_factory=None,
                 now_fn=None, alert_sink=None):
        self.settings = settings
        self.client_factory = client_factory or (lambda: None)
        self.llm_factory = llm_factory
        self.now_fn = now_fn or datetime.now
        # alert_sink(message) — default: print. Tests inject a list-append.
        self.alert_sink = alert_sink or (lambda msg: print(msg))
        self.episodes: dict[str, Episode] = {}
        self.sent_alerts: list[str] = []
        self._ids = itertools.count(1)

    # -- plumbing ------------------------------------------------------
    def _episode(self, vehicle: str) -> Episode:
        return self.episodes.setdefault(vehicle, Episode())

    def _llm(self):
        if self.llm_factory is not None:
            return self.llm_factory()
        if self.settings.ai_mode == "never":
            return None
        if not self.settings.ai_base_url:
            return None
        return LlmBackend(self.settings.ai_base_url, self.settings.ai_api_key,
                          self.settings.ai_model, self.settings.ai_timeout_seconds)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{int(time.time())}-{next(self._ids)}"

    def _notify(self, message: str) -> str:
        if self.settings.dry_run:
            return "dry run — alert not sent"
        dest = self.settings.alert_destination or "(no alert destination set — printed only)"
        full = f"[Cabin Sentinel → {dest}] {message}"
        self.sent_alerts.append(full)
        try:
            self.alert_sink(full)
        except Exception:
            pass
        return f"sent to {dest}"

    # -- detection -------------------------------------------------------
    def check_frame(self, frame: CabinFrame, execute: bool = True) -> dict:
        """Evaluate one frame, advance the episode, notify if it alerts."""
        ep = self._episode(frame.vehicle)
        if ep.acknowledged and frame.occupant in ("child", "pet"):
            # Owner already confirmed they are handling it: keep watching,
            # don't re-alert on the same episode.
            detection, ep.alone_since, ep.alerted_at = next_episode_state(
                frame, self.settings, ep.alone_since, ep.alerted_at)
            detection = type(detection)(
                state="WATCH" if detection.state in ("ALERT", "ESCALATED")
                else detection.state,
                summary=(detection.summary + " (You already acknowledged "
                         "this — no repeat alert.)")
                if detection.state in ("ALERT", "ESCALATED") else detection.summary,
                reasons=detection.reasons, actions=["log_watch"],
                alone_minutes=detection.alone_minutes, notify=False)
        else:
            detection, ep.alone_since, ep.alerted_at = next_episode_state(
                frame, self.settings, ep.alone_since, ep.alerted_at)
        ep.last_detection = detection
        ep.history.append((frame.timestamp, detection.state, detection.summary))
        status = "logged"
        if detection.notify and execute:
            status = self._notify(detection.summary)
        return {"detection": detection, "status": status,
                "vehicle": frame.vehicle}

    def acknowledge(self, vehicle: str) -> str:
        ep = self._episode(vehicle)
        if ep.alerted_at is None and not ep.alone_since:
            return f"No active alert for {vehicle} — nothing to acknowledge."
        ep.acknowledged = True
        ep.alerted_at = None
        return (f"Acknowledged for {vehicle}. I won't repeat the alert for "
                f"this episode — go check on them, and I'll keep watching.")

    def reset_episode(self, vehicle: str) -> None:
        self.episodes[vehicle] = Episode()

    def status_text(self, vehicle: str = "") -> str:
        names = [vehicle] if vehicle else [v.name for v in self.settings.vehicles]
        if not names:
            names = ["(no cars configured yet)"]
        lines = []
        for name in names:
            ep = self.episodes.get(name)
            if ep is None or ep.last_detection is None:
                lines.append(f"{name}: no cabin check yet.")
            else:
                d = ep.last_detection
                lines.append(f"{name}: {d.state} — {d.summary}")
        return "\n".join(lines)

    # -- OpenAI surface --------------------------------------------------
    def models_list(self) -> dict:
        return {"object": "list", "data": [{
            "id": self.settings.model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "tesla-cabin-sentinel",
        }]}

    def _vehicle_for(self, text: str) -> str:
        low = text.lower()
        for v in self.settings.vehicles:
            if v.name.lower() in low:
                return v.name
        if self.settings.vehicles:
            return self.settings.vehicles[0].name
        return "Model Y"

    def chat_completions(self, body: dict) -> dict:
        messages = body.get("messages") or []
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content") or ""
                if isinstance(content, list):  # vision-shaped messages
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                parts.append(str(part.get("text", "")))
                            elif part.get("type") == "image_url":
                                parts.append("[cabin frame image attached]")
                    user_text = " ".join(parts)
                else:
                    user_text = str(content)
                break
        low = user_text.lower()
        if any(h in low for h in _ACK_HINTS):
            text = self.acknowledge(self._vehicle_for(user_text))
        elif any(h in low for h in _CHECK_HINTS):
            frame = parse_frame(user_text, self.settings,
                                self._vehicle_for(user_text))
            frame.timestamp = self.now_fn()
            outcome = self.check_frame(frame)
            d = outcome["detection"]
            text = (f"{d.summary}\nStatus: {d.state} — "
                    f"alert action: {outcome['status']}.")
            if d.actions:
                text += f"\nActions: {', '.join(d.actions)}."
        else:
            text = self._llm_answer(user_text)
        return {
            "id": self._next_id("chatcmpl"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.settings.model_id,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                      "total_tokens": 0},
        }

    def embeddings(self, body: dict) -> dict:
        raw = body.get("input", "")
        texts = raw if isinstance(raw, list) else [raw]
        data = []
        for i, t in enumerate(texts):
            data.append({
                "object": "embedding",
                "index": i,
                "embedding": embed_text(str(t), self.settings.embedding_dim),
            })
        return {
            "object": "list",
            "data": data,
            "model": self.settings.model_id,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    # -- LLM path ---------------------------------------------------------
    def _context(self) -> str:
        s = self.settings
        lines = [
            f"Sentinel settings: alert after {s.alert_after_minutes} minute(s) "
            f"alone; escalate after {s.escalate_after_minutes} minute(s) "
            f"unanswered; danger temperature {s.danger_temp_f}°F; "
            f"confidence threshold {s.confidence_threshold}%; "
            f"alert destination: {s.alert_destination or 'not set'}.",
            "FUTURE-API HONESTY: Tesla's Fleet API has no cabin camera or "
            "rear-occupant endpoint today. Live car checks are proposed, "
            "not available.",
        ]
        for name, ep in self.episodes.items():
            if ep.last_detection is not None:
                lines.append(f"Latest for {name}: {ep.last_detection.state} — "
                             f"{ep.last_detection.summary}")
        return "\n".join(lines)

    def _llm_answer(self, user_text: str) -> str:
        llm = self._llm()
        if llm is None:
            return CAPABILITY_BLURB
        try:
            reply = llm.chat(self._context(), user_text)
        except Exception:
            return CAPABILITY_BLURB + " (The AI backend didn't respond just now.)"
        cmd = extract_command(reply)
        if cmd is None:
            return reply
        vehicle = None
        needle = cmd["vehicle"].lower()
        for v in self.settings.vehicles:
            if needle in v.name.lower() or v.name.lower() in needle:
                vehicle = v
                break
        if vehicle is None:
            names = ", ".join(v.name for v in self.settings.vehicles) or "(none yet)"
            return (f"I couldn't match \"{cmd['vehicle']}\" to one of your "
                    f"cars. Your cars: {names}.")
        return self._execute_llm_command(cmd, vehicle)

    def _execute_llm_command(self, cmd: dict, vehicle) -> str:
        name = cmd["command"]
        if name in PROPOSED_COMMANDS:
            return (f"{name} is a proposed Tesla API feature that doesn't "
                    "exist yet — simulated only, nothing was sent to the car.")
        if self.settings.dry_run:
            return f"Dry run: would run {name} for {vehicle.name} — nothing changed."
        if name == "send_alert":
            msg = cmd.get("params", {}).get("message") or (
                f"Cabin Sentinel alert for {vehicle.name} — please check "
                f"the car.")
            return f"Alert: {self._notify(msg)}."
        if name == "acknowledge_alert":
            return self.acknowledge(vehicle.name)
        if name == "log_event":
            return "Logged."
        return f"Unknown command {name} — dropped."
