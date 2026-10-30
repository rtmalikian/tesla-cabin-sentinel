"""The setup wizard must produce a config the app can load — no developer
knowledge required from the (scripted) user."""
import os

import pytest

from tesla_cabin_sentinel.config import load_settings
from tesla_cabin_sentinel.setup import run_setup


def _scripted(answers):
    it = iter(answers)

    def ask(prompt):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"wizard asked for more input: {prompt!r}")

    return ask


def _load_env(path):
    env = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def test_wizard_defaults_produce_loadable_config(tmp_path):
    # Car name + VIN, then Enter through every default, ntfy default topic,
    # AI auto defaults.
    answers = ["Model Y", "", "", "", "", "1", "", "1", "", ""]
    path = run_setup(input_fn=_scripted(answers), print_fn=lambda *a: None,
                     env_path=str(tmp_path / ".env"))
    s = load_settings(_load_env(path))
    assert s.vehicles[0].name == "Model Y"
    assert s.alert_after_minutes == 2
    assert s.escalate_after_minutes == 5
    assert s.danger_temp_f == 95
    assert s.alert_destination == "ntfy://family-car-alerts"
    assert s.ai_mode == "auto"


def test_wizard_custom_answers_round_trip(tmp_path):
    answers = ["Blue", "5YJ123", "0", "3", "100", "3", "2", "gpt-test"]
    path = run_setup(input_fn=_scripted(answers), print_fn=lambda *a: None,
                     env_path=str(tmp_path / ".env"))
    s = load_settings(_load_env(path))
    assert s.vehicles[0].name == "Blue"
    assert s.vehicles[0].vin == "5YJ123"
    assert s.alert_after_minutes == 0
    assert s.escalate_after_minutes == 3
    assert s.danger_temp_f == 100
    assert s.alert_destination == ""  # "print alerts here" choice
    assert s.ai_mode == "never"
    assert s.ai_model == "gpt-test"


def test_wizard_rejects_bad_choice_then_accepts(tmp_path):
    answers = ["Model Y", "", "", "", "", "9", "1", "", "1", "", ""]
    path = run_setup(input_fn=_scripted(answers), print_fn=lambda *a: None,
                     env_path=str(tmp_path / ".env"))
    assert os.path.exists(path)
