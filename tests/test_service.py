from datetime import datetime

from tesla_cabin_sentinel.config import Settings, VehicleConfig
from tesla_cabin_sentinel.detection import CabinFrame
from tesla_cabin_sentinel.llm import extract_command
from tesla_cabin_sentinel.service import (
    CabinSentinelService, parse_frame)

T0 = datetime(2026, 10, 30, 13, 0, 0)


def _service(**overrides):
    s = Settings(vehicles=[VehicleConfig("Model Y", "VINY")],
                 ai_mode="never")
    for k, v in overrides.items():
        setattr(s, k, v)
    sent = []
    svc = CabinSentinelService(s, now_fn=lambda: T0,
                               alert_sink=sent.append)
    return svc, sent


def test_models_shape():
    svc, _ = _service()
    data = svc.models_list()
    assert data["object"] == "list"
    assert data["data"][0]["id"] == "tesla-cabin-sentinel"


def test_embeddings_shape_and_determinism():
    svc, _ = _service()
    out = svc.embeddings({"input": "child left in Model Y"})
    vec = out["data"][0]["embedding"]
    assert len(vec) == 384
    assert out["data"][0]["object"] == "embedding"
    again = svc.embeddings({"input": "child left in Model Y"})
    assert again["data"][0]["embedding"] == vec
    other = svc.embeddings({"input": "forgotten bag"})
    assert other["data"][0]["embedding"] != vec


def test_chat_frame_description_alerts_and_notifies():
    svc, sent = _service(alert_after_minutes=0)
    resp = svc.chat_completions({"messages": [
        {"role": "user",
         "content": "child alone in the Model Y, cabin 88 degrees"}]})
    text = resp["choices"][0]["message"]["content"]
    assert resp["object"] == "chat.completion"
    assert "ALERT" in text
    assert len(sent) == 1  # one real alert delivered to the sink


def test_chat_vision_shaped_message_accepted():
    svc, _ = _service(alert_after_minutes=0)
    resp = svc.chat_completions({"messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "pet alone in the Model Y"},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]}]})
    assert "ALERT" in resp["choices"][0]["message"]["content"]


def test_chat_item_is_watch_not_alert():
    svc, sent = _service()
    resp = svc.chat_completions({"messages": [
        {"role": "user", "content": "forgotten bag in the Model Y"}]})
    assert "WATCH" in resp["choices"][0]["message"]["content"]
    assert sent == []


def test_acknowledge_suppresses_repeat_alerts():
    svc, sent = _service(alert_after_minutes=0)
    svc.check_frame(CabinFrame(vehicle="Model Y", occupant="child",
                               confidence=95, timestamp=T0))
    assert len(sent) == 1
    assert "Acknowledged" in svc.acknowledge("Model Y")
    svc.check_frame(CabinFrame(vehicle="Model Y", occupant="child",
                               confidence=95, timestamp=T0))
    assert len(sent) == 1  # no repeat alert for the same episode


def test_acknowledge_with_no_alert_says_so():
    svc, _ = _service()
    assert "No active alert" in svc.acknowledge("Model Y")


def test_dry_run_never_sends():
    svc, sent = _service(alert_after_minutes=0, dry_run=True)
    outcome = svc.check_frame(CabinFrame(vehicle="Model Y", occupant="child",
                                         confidence=95, timestamp=T0))
    assert outcome["detection"].state == "ALERT"
    assert outcome["status"].startswith("dry run")
    assert sent == [] and svc.sent_alerts == []


def test_llm_command_allowlist():
    good = extract_command(
        "```json\n{\"command\": \"send_alert\", \"vehicle\": \"Model Y\", "
        "\"params\": {}}\n```")
    assert good["command"] == "send_alert"
    assert extract_command(
        "```json\n{\"command\": \"unlock_doors\", \"vehicle\": \"Model Y\", "
        "\"params\": {}}\n```") is None
    assert extract_command(
        "```json\n{\"command\": \"send_alert\", \"vehicle\": \"\", "
        "\"params\": {}}\n```") is None
    assert extract_command("no json block here") is None


def test_llm_proposed_command_is_simulated_only():
    svc, _ = _service()
    out = svc._execute_llm_command(
        {"command": "request_cabin_check", "vehicle": "Model Y", "params": {}},
        svc.settings.vehicles[0])
    assert "proposed" in out and "simulated" in out


def test_llm_send_alert_command_notifies():
    svc, sent = _service()
    out = svc._execute_llm_command(
        {"command": "send_alert", "vehicle": "Model Y",
         "params": {"message": "test alert"}}, svc.settings.vehicles[0])
    assert "sent" in out and len(sent) == 1


def test_parse_frame_reads_plain_words():
    s = Settings()
    f = parse_frame("dog alone, 55% sure, cabin 100 degrees, unlocked",
                    s, "Model Y")
    assert f.occupant == "pet" and f.confidence == 55
    assert f.cabin_temp_f == 100 and not f.locked
    f = parse_frame("child with an adult in the car", s, "Model Y")
    assert f.occupant == "child" and f.adult_present
    f = parse_frame("left my laptop in the car", s, "Model Y")
    assert f.occupant == "item" and f.item_kind == "laptop"


def test_no_backend_falls_back_to_capability_blurb():
    svc, _ = _service()
    resp = svc.chat_completions({"messages": [
        {"role": "user", "content": "tell me about yourself"}]})
    text = resp["choices"][0]["message"]["content"]
    assert "no cabin camera" in text  # honesty note, not an error
