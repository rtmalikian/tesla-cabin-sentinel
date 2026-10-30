"""CLI: tcsentinel setup | serve | preview | check | acknowledge | simulate"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

from .config import ConfigError, load_settings
from .detection import CabinFrame

__version__ = "0.1.0"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")


def _service(settings):
    from .service import CabinSentinelService
    return CabinSentinelService(settings)


def cmd_setup(args, settings) -> int:
    from .setup import run_setup
    run_setup()
    return 0


def cmd_serve(args, settings) -> int:
    from .server import serve
    service = _service(settings)
    print("Vehicle and cabin data go ONLY to your configured LLM backend "
          f"(TCS_AI_BASE_URL={settings.ai_base_url or 'none'}).")
    print("Honesty note: Tesla exposes no cabin camera today — live car "
          "checks are a proposed feature (see API_PROPOSAL.md).")
    serve(service)
    return 0


def _frame_from_args(args, settings):
    vehicle = args.vehicle or (
        settings.vehicles[0].name if settings.vehicles else "Model Y")
    occupant = args.occupant
    item_kind = args.item if occupant == "item" else ""
    return CabinFrame(
        vehicle=vehicle, occupant=occupant, confidence=args.confidence,
        item_kind=item_kind, parked=not args.driving, locked=not args.unlocked,
        driving=args.driving, cabin_temp_f=args.temp,
        climate_on=args.climate_on,
        adult_present=args.with_adult, timestamp=datetime.now())


def cmd_preview(args, settings) -> int:
    """Plain-English dry run: exactly what WOULD happen, before anything real."""
    service = _service(settings)
    frame = _frame_from_args(args, settings)
    outcome = service.check_frame(frame, execute=False)
    d = outcome["detection"]
    print("PREVIEW — nothing has been alerted, nothing changed.")
    print("")
    print(d.summary)
    print(f"State: {d.state}")
    if d.reasons:
        print("Why: " + "; ".join(d.reasons) + ".")
    if d.actions:
        print("What would happen: " + ", ".join(d.actions) + ".")
    print("")
    print("Happy with that? Run `tcsentinel check` with the same options "
          "to assess for real, or describe the frame to the chat server.")
    return 0


def cmd_check(args, settings) -> int:
    service = _service(settings)
    frame = _frame_from_args(args, settings)
    outcome = service.check_frame(frame)
    d = outcome["detection"]
    print(d.summary)
    print(f"State: {d.state} — alert action: {outcome['status']}.")
    return 0


def cmd_acknowledge(args, settings) -> int:
    service = _service(settings)
    vehicle = args.vehicle or (
        settings.vehicles[0].name if settings.vehicles else "Model Y")
    print(service.acknowledge(vehicle))
    return 0


def cmd_simulate(_args, settings) -> int:
    from .simulator import render_demo, run_demo
    print(render_demo(run_demo(settings)))
    return 0


def _add_frame_args(p):
    p.add_argument("--vehicle", default=None,
                   help="Car nickname (default: first car in your settings)")
    p.add_argument("--occupant", default="child",
                   choices=["child", "pet", "adult", "item", "none"],
                   help="Who the cabin check sees (default: child)")
    p.add_argument("--item", default="",
                   help="Forgotten-item kind when --occupant item (bag, phone...)")
    p.add_argument("--confidence", type=int, default=100,
                   help="Detector confidence 0-100 (default 100)")
    p.add_argument("--temp", type=float, default=None,
                   help="Cabin temperature in °F")
    p.add_argument("--climate-on", action="store_true",
                   help="Dog Mode / Keep Climate On is running")
    p.add_argument("--with-adult", action="store_true",
                   help="An adult is present with the occupant")
    p.add_argument("--unlocked", action="store_true",
                   help="The car is NOT locked")
    p.add_argument("--driving", action="store_true",
                   help="The car is driving, not parked")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tcsentinel",
        description="Cabin Sentinel — rear-occupant safety for parked Teslas "
                    "(FUTURE-API: Tesla exposes no cabin camera yet).")
    p.add_argument("--version", action="version", version=f"tcsentinel {__version__}")
    p.add_argument("--env-file", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Guided first-run setup (plain-language questions)")
    sub.add_parser("serve", help="Run the OpenAI-compatible API server")
    prev = sub.add_parser("preview", help="Plain-English dry run (alerts nothing)")
    _add_frame_args(prev)
    chk = sub.add_parser("check", help="Assess one cabin frame for real")
    _add_frame_args(chk)
    ack = sub.add_parser("acknowledge", help="Acknowledge the current alert for a car")
    ack.add_argument("--vehicle", default=None)
    sub.add_parser("simulate", help="Demo with pretend cars and cabin events (no API calls)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
    else:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    try:
        settings = load_settings(dict(os.environ))
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2
    handlers = {"setup": cmd_setup, "serve": cmd_serve,
                "preview": cmd_preview, "check": cmd_check,
                "acknowledge": cmd_acknowledge, "simulate": cmd_simulate}
    try:
        return handlers[args.command](args, settings)
    except Exception as exc:  # human error messages, never a stack trace
        print(f"Something went wrong: {exc}. Check your settings with "
              "`tcsentinel setup`, then try again.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
