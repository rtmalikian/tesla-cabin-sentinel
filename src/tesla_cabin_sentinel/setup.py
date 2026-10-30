"""Guided first-run setup: plain-language questions, writes .env itself.

Built for Tesla owners, not developers — defaults everywhere, numbered
choices, times in plain words ("2 minutes"), cars picked by nickname (a
VIN is optional and explained in owner words). No hand-edited config
syntax: re-run `tcsentinel setup` any time to change an answer.

`run_setup` takes injectable input/print functions so tests can feed
scripted answers and assert the written config loads.
"""
from __future__ import annotations

import os


def _ask(prompt: str, default: str, ask, out) -> str:
    shown = f"{prompt} [{default}]: " if default else f"{prompt}: "
    answer = ask(shown).strip()
    return answer or default


def _choice(prompt: str, options: list[tuple[str, str]], ask, out) -> str:
    out(prompt)
    for i, (_key, label) in enumerate(options, 1):
        out(f"  {i}) {label}")
    while True:
        raw = ask(f"Pick a number (1-{len(options)}) [1]: ").strip() or "1"
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        out("That's not one of the numbers above — try again.")


def _int_choice(prompt: str, default: int, ask, out) -> int:
    while True:
        raw = _ask(prompt, str(default), ask, out)
        if raw.isdigit():
            return int(raw)
        out("Please type a whole number of minutes.")


def run_setup(input_fn=input, print_fn=print, env_path: str = ".env") -> str:
    ask, out = input_fn, print_fn
    out("")
    out("Cabin Sentinel setup — I'll ask a few plain questions and write")
    out("your settings file for you. Press Enter to accept anything in")
    out("[brackets]. You can re-run this any time to change an answer.")
    out("")
    out("IMPORTANT, PLEASE READ: Tesla's Fleet API has no cabin camera")
    out("or rear-occupant sensor today, so live checks of a real car are")
    out("not possible yet. This setup prepares the monitor, the alerts")
    out("and the simulator, ready for the day Tesla ships the API.")
    out("")

    car = _ask("What do you call your car? (e.g. Model Y, Blue)",
               "Model Y", ask, out)
    vin = _ask("Its VIN, if you know it (in the Tesla app under Controls → "
               "Software; leave blank if not)",
               "", ask, out)
    out("")
    out("When a child or pet is left alone in the parked car, how should")
    out("alerts work? A parked car heats up fast, so the defaults are short.")
    alert_after = _int_choice(
        "How many minutes alone before the first alert? (0 = right away)",
        2, ask, out)
    escalate_after = _int_choice(
        "If that alert goes unanswered, how many minutes later should it "
        "escalate to your second contact?", 5, ask, out)
    danger_temp = _int_choice(
        "At what cabin temperature (°F) should an alert skip straight to "
        "escalation, no waiting?", 95, ask, out)
    out("")
    out("Where should alerts go? An ntfy.sh topic is free and takes a")
    out("minute to set up (install the ntfy app, pick a topic name).")
    dest_kind = _choice("How do you want to receive alerts?", [
        ("ntfy", "ntfy.sh phone notification (recommended, free)"),
        ("webhook", "A webhook URL of my own"),
        ("print", "Just print alerts here for now"),
    ], ask, out)
    destination = ""
    if dest_kind == "ntfy":
        topic = _ask("Your ntfy topic name (letters, numbers and dashes; "
                     "e.g. family-car-alerts)", "family-car-alerts", ask, out)
        destination = f"ntfy://{topic}"
    elif dest_kind == "webhook":
        destination = _ask("Your webhook URL", "", ask, out)
    out("")
    ai_mode = _choice("Should the chat server use an AI backend (local "
                      "Ollama by default) to explain assessments?", [
        ("auto", "Yes, when one is available (falls back to built-in answers)"),
        ("never", "No — built-in answers only, nothing leaves this computer"),
    ], ask, out)
    ai_url = "http://localhost:11434/v1"
    if ai_mode == "auto":
        ai_url = _ask("Your AI server address (an OpenAI-compatible API)",
                      ai_url, ask, out)
    ai_model = _ask("Which model name should it use?", "llama3.1", ask, out)

    lines = [
        "# Written by `tcsentinel setup` — edit by re-running setup any time.",
        "# FUTURE-API NOTE: Tesla exposes no cabin camera today; see API_PROPOSAL.md.",
        "",
        "TESLA_CLIENT_ID=",
        "TESLA_CLIENT_SECRET=",
        "TESLA_REGION=na",
        "TESLA_REDIRECT_URI=http://localhost:8080/callback",
        "",
        f"TCS_VEHICLES={car}={vin}",
        "",
        "TCS_SERVER_HOST=127.0.0.1",
        "TCS_SERVER_PORT=8645",
        "TCS_SERVER_API_KEY=",
        "TCS_MODEL_ID=tesla-cabin-sentinel",
        "",
        f"TCS_AI_BASE_URL={ai_url}",
        "TCS_AI_API_KEY=",
        f"TCS_AI_MODEL={ai_model}",
        f"TCS_AI_MODE={ai_mode}",
        "TCS_AI_TIMEOUT_SECONDS=20",
        "TCS_EMBEDDING_DIM=384",
        "TCS_TOKEN_FILE=~/.tcs/tokens.json",
        "TCS_DATA_DIR=~/.tcs",
        "TCS_DRY_RUN=0",
        "",
        f"TCS_ALERT_DESTINATION={destination}",
        f"TCS_ALERT_AFTER_MINUTES={alert_after}",
        f"TCS_ESCALATE_AFTER_MINUTES={escalate_after}",
        "TCS_CHECK_INTERVAL_MINUTES=1",
        "TCS_CONFIDENCE_THRESHOLD=70",
        f"TCS_DANGER_TEMP_F={danger_temp}",
        "TCS_CLIMATE_SAFE_MAX_F=85",
        "",
    ]
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    out("")
    out(f"Done — settings written to {os.path.abspath(env_path)}.")
    out("Next steps:")
    out("  1) tcsentinel simulate  — see the monitor handle pretend "
        "cabin events")
    out("  2) tcsentinel preview   — a plain-English dry run of one check")
    out("  3) tcsentinel serve     — start the AI chat server")
    return os.path.abspath(env_path)
