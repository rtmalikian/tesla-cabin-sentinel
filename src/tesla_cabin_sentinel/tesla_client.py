"""Future-API placeholder for the Tesla Fleet API client.

Tesla's Fleet API exposes NO cabin camera, rear-occupant, or cabin
occupancy endpoint today, so there is nothing here to call yet — and
this module refuses to pretend otherwise. When Tesla ships the endpoints
proposed in API_PROPOSAL.md, this is where `cabin_snapshot` and
`cabin_occupancy` calls will live, next to the standard OAuth + vehicle
commands every other app in the series uses.

Until then, any attempt to check a real car raises FutureApiError with a
plain-language explanation and a pointer to the simulator, which is the
supported way to see the product work today.
"""
from __future__ import annotations


class FutureApiError(Exception):
    """Raised when code asks a real car for data the Fleet API can't give."""


class TeslaClient:
    """Stub kept deliberately tiny: no tokens, no HTTP, no fake success."""

    def __init__(self, *args, **kwargs):
        pass

    def authorize_url(self) -> str:
        return ("https://developer.tesla.com/docs/fleet-api "
                "(pairing is for future commands; cabin checks need the "
                "proposed API first — see API_PROPOSAL.md)")

    def cabin_snapshot(self, vin: str):
        raise FutureApiError(
            "Tesla's Fleet API has no cabin camera endpoint yet, so a real "
            "car can't be checked. Run `tcsentinel simulate` to see the "
            "monitor work on pretend cabin frames, and read "
            "API_PROPOSAL.md for the endpoints Tesla would need to add.")

    def cabin_occupancy(self, vin: str):
        raise FutureApiError(
            "Tesla's Fleet API has no rear-occupant sensor endpoint yet. "
            "Use `tcsentinel simulate` for the demo, or describe a frame "
            "to the chat server (\"child alone in the Model Y\") to see an "
            "assessment.")
