# API Proposal — cabin occupancy sensing for the Tesla Fleet API

**Status:** proposal. None of the endpoints below exist in the Fleet API
today. Cabin Sentinel models all of them in its simulator, labels them
"proposed API" everywhere they appear, and never sends them to a real car.

## The gap

Hyundai and Kia have shipped rear-occupant alerts for years; Tesla has
none. Worse, Tesla exposes no cabin camera feed and no occupancy signal
at all through the Fleet API, so no third-party app can build one either.
Every year, children and pets die in hot parked cars — almost always
because a busy adult genuinely forgot they were there, not because
anyone chose to leave them. A car that already has interior cameras and
a cabin temperature sensor could catch that mistake in minutes.

## 1. `cabin_occupancy` — a data endpoint, not a camera feed

Privacy-first: most owners do not want raw cabin images leaving their
car. The endpoint should return a *classification*, computed on-device,
not a picture:

```
GET /api/1/vehicles/{vehicle_tag}/vehicle_data
  → cabin_occupancy: {
      "occupant": "child" | "pet" | "adult" | "item" | "none",
      "confidence": 0-100,
      "item_kind": "bag" | "phone" | "laptop" | "keys" | "stroller" | null,
      "zones": ["rear_left", "rear_right"],   // where the occupant sits
      "updated_at": "2026-10-30T13:00:00Z"
    }
```

Notes:

- Classification runs on the car's own computer; no image ever leaves
  the vehicle through this endpoint.
- A separate, owner-opt-in `cabin_snapshot` (single still, explicit
  consent per request, rate-limited) is the *only* way an image should
  ever be retrievable, for owners who want to see for themselves before
  breaking a window.
- `confidence` is load-bearing: Cabin Sentinel treats anything below
  the owner's threshold as a watch, never an alert, and an uncertain
  "empty" reading never closes an open alert episode.

## 2. `cabin_alert` — owner-configured escalation hooks

Once occupancy is known, the car (or an app like this one) needs a way
to reach a human loudly:

```
POST /api/1/vehicles/{vehicle_tag}/command/cabin_alert
{
  "level": "notify" | "escalate",   // escalate = horn + hazard flash
  "message": "Child detected alone in the parked car"
}
```

Response mirrors existing commands (`{"result": true, "reason": ""}`).
`escalate` maps to the car's existing horn/hazard hardware — the same
hardware Sentry Mode already drives — so no new actuators are needed.

## 3. What already exists, and what this reuses

- Cabin temperature: already in `climate_state` (`inside_temp`) — Cabin
  Sentinel's danger-temperature rule needs nothing new.
- Dog Mode / Keep Climate On: already controllable — the "pet is safe
  with climate on" rule needs nothing new.
- Horn/hazards: already drivable via `actuate_horn` and Sentry — the
  escalation step needs nothing new.
- Locked/parked/driving state: already in `vehicle_data` — the
  "alone in a locked, parked car" precondition needs nothing new.

The *only* genuinely new capability is the occupancy classification
itself. Everything else in this product is plumbing around data Tesla
already exposes.

## Why this is safe to add

- No vehicle motion, no locks, no driving controls are involved.
- Occupancy classification is computed on-device; no images leave the
  car by default.
- The endpoint is read-only data plus one alert command; an app cannot
  use it to watch occupants — it can only learn "someone vulnerable is
  alone" and shout about it.
- False positives are bounded by design: confidence thresholds,
  grace periods, and the rule that uncertain readings never alert and
  never close an open episode.

## What Cabin Sentinel does today, without these endpoints

The full product ships anyway: the detection brain (grace period →
alert → escalation, danger-temperature shortcut, Dog Mode pet pass,
forgotten-item reminders), the OpenAI-compatible chat endpoint that
assesses frames described in plain words (including vision-shaped
messages with an attached frame), the alert ladder, and a simulator
running six scenarios over virtual time. The day these endpoints land,
`tesla_client.py` gains two methods and the simulator's frames become
real readings — nothing else changes.
