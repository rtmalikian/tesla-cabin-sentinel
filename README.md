# Tesla Cabin Sentinel — Rear-Occupant Alert for Parked Teslas (Model 3, Model Y, Model S, Model X, Cybertruck)

**Free, open-source Tesla Fleet API app that watches for a child or pet left alone in a parked car — alerts you after a short grace period, and escalates if the alert goes unanswered or the cabin gets dangerously hot.**

▶ **[Try the live demo](https://rtmalikian.github.io/tesla-cabin-sentinel/)** — pick a cabin scenario (child left behind, hot cabin, Dog Mode pet, forgotten bag…) and watch the alert ladder run. Pretend data only, no install, no car needed.

## Why?

Hyundai and Kia ship rear-occupant alerts. Tesla has none — and exposes no cabin camera for anyone else to build one with, either. Every year, children and pets die in hot parked cars, almost always because a busy adult genuinely forgot they were back there. A car with interior cameras and a temperature sensor could catch that mistake in minutes.

So Cabin Sentinel ships the full product anyway — the detection brain, the alert ladder, the AI endpoint, the simulator — plus the `API_PROPOSAL.md` Tesla would need, ready the day the API lands.

**No AI needed:** the detection rules, the alert ladder, and the simulator all work with zero AI involved. The optional AI layer only powers free-form chat — the rules engine always decides.

## How it works

The alert ladder, in plain English:

```
Child buckled in the back seat, car parked and locked
  1:00 PM  Child alone — grace period running (default 2 minutes)
  1:02 PM  Grace period over → ALERT sent to you
  1:07 PM  No acknowledgement → ESCALATED to your second contact
  (any time the cabin hits 95°F → straight to ESCALATED, no waiting)
  Cabin empty again → episode clears, all quiet
```

And the cases that deliberately do **not** alert:

- **Pet with Dog Mode on** and the cabin at a safe temperature → watch, not alert.
- **Uncertain detection** (below your confidence threshold) → watch, never alert — and an uncertain "empty" reading never closes an open alert.
- **Forgotten bag / phone / laptop** → a reminder, never an alarm.
- **Child with an adult present**, or the car driving → all clear.
- **A child alone always alerts, climate on or not.** Dog Mode excuses a pet, never a child.

## Quickstart (owners, not developers)

```bash
git clone https://github.com/rtmalikian/tesla-cabin-sentinel.git
cd tesla-cabin-sentinel
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
tcsentinel setup      # plain-language questions; writes .env for you
tcsentinel simulate   # see the monitor handle pretend cabin events
tcsentinel preview --occupant child --temp 88   # dry run of one check
tcsentinel serve      # start the OpenAI-compatible chat server
```

What you'll see when it works: `simulate` prints six scenarios with the alert ladder running on each, ending in `Total alerts sent` and a $0.00 API cost line. `preview` prints one plain-English assessment and says what *would* happen — it alerts nothing.

## Tesla developer setup

When the proposed cabin endpoints land, live checks will use the standard Fleet API flow: create an app at developer.tesla.com, authorize once, pair a virtual key (`tcsentinel` will print the pairing link). Until then, `simulate` and the chat server's frame descriptions are the supported ways to use the product. No car connection is needed for any of that.

## `.env` reference

| Variable | Default | What it means |
|---|---|---|
| `TCS_VEHICLES` | — | Your cars, `nickname=VIN` pairs (VIN optional) |
| `TCS_ALERT_DESTINATION` | — | Where alerts go: `ntfy://your-topic` or a webhook URL; blank = print only |
| `TCS_ALERT_AFTER_MINUTES` | 2 | Minutes alone before the first alert (0 = right away) |
| `TCS_ESCALATE_AFTER_MINUTES` | 5 | Minutes unanswered before escalation |
| `TCS_CHECK_INTERVAL_MINUTES` | 1 | How often the (future) cabin check runs while parked |
| `TCS_CONFIDENCE_THRESHOLD` | 70 | Detector confidence (0–100) treated as a real occupant |
| `TCS_DANGER_TEMP_F` | 95 | Cabin temp that skips straight to escalation |
| `TCS_CLIMATE_SAFE_MAX_F` | 85 | With climate on at/below this, a pet alone is a watch |
| `TCS_AI_BASE_URL` / `TCS_AI_MODEL` / `TCS_AI_MODE` | Ollama / llama3.1 / auto | Pluggable LLM backend; `never` = built-in answers only |
| `TCS_SERVER_HOST` / `TCS_SERVER_PORT` | 127.0.0.1 / 8645 | The chat server's address |
| `TCS_SERVER_API_KEY` | — | Optional bearer token for the server |
| `TCS_DRY_RUN` | 0 | 1 = plan and assess, never send an alert |

## AI endpoints

Cabin Sentinel exposes an OpenAI-compatible surface (stdlib HTTP server, no framework). Vehicle and cabin data go **only** to your configured LLM backend, nowhere else.

```bash
# What models are available?
curl http://127.0.0.1:8645/v1/models

# Assess a cabin frame in plain words (vision-shaped messages welcome:
# send a text part plus an image_url part and the frame is assessed).
curl http://127.0.0.1:8645/v1/chat/completions -d '{
  "model": "tesla-cabin-sentinel",
  "messages": [{"role": "user",
    "content": "child alone in the Model Y, cabin 98 degrees"}]}'

# Acknowledge the current alert for a car:
curl http://127.0.0.1:8645/v1/chat/completions -d '{
  "model": "tesla-cabin-sentinel",
  "messages": [{"role": "user",
    "content": "acknowledge the Model Y alert, I am on my way"}]}'

# Embeddings over cabin-event text (local deterministic hashing, dim 384):
curl http://127.0.0.1:8645/v1/embeddings -d '{
  "input": "child left in parked Model Y"}'
```

LLM-emitted commands are validated against a strict allowlist (`send_alert`, `acknowledge_alert`, `request_cabin_check`, `log_event`) before anything runs; `request_cabin_check` is a proposed API command and is always labelled simulated. Dry-run is honored everywhere.

## Expected API cost

**$0.00 while the cabin endpoints don't exist** — the simulator and the chat assessments make no live calls. When Tesla ships the proposed endpoints, a parked car checked once a minute costs only data calls (no wakes, no commands) while parked — the expensive calls are wakes and commands, and this app issues neither to a parked car.

## FAQ

**Does this work with my real Tesla today?**
Not for live checks — Tesla's Fleet API exposes no cabin camera or rear-occupant sensor, and this app refuses to pretend otherwise. The detection brain, alerts, chat endpoint and simulator are all real now; the car check plugs in the day the API lands (see `API_PROPOSAL.md`).

**Will it false-alarm on a bag on the back seat?**
No. A forgotten item is a reminder, never an alarm, and low-confidence detections never alert at all.

**What if my dog is in the car with Dog Mode on?**
That's a watch, not an alert — as long as the climate is running and the cabin stays at a safe temperature. If the cabin heats past your danger temperature, it escalates anyway.

**What if I acknowledge the alert but I'm still a few minutes away?**
Acknowledging stops repeat alerts for that episode, and the monitor keeps watching. If the cabin empties, the episode clears on its own.

**Does it send pictures of my car's interior anywhere?**
No. The proposed API itself is designed so classification runs on the car and no image ever leaves it by default. This app stores nothing but your settings and the alert history on your own machine.

**Why is the grace period only 2 minutes by default?**
A parked car in sun heats shockingly fast — a child's body temperature rises 3–5× faster than an adult's. Two minutes is short on purpose; you can raise it in setup, but we don't recommend it.

## Safety note

Cabin Sentinel is a backup for human attention, not a replacement for it — always check the back seat. It is free, open-source software (MIT), not a safety-certified device, and it cannot check a real car until Tesla ships the endpoints in `API_PROPOSAL.md`.

## License

MIT — Raphael Malikian.
