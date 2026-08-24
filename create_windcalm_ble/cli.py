"""Command-line interface for controlling the WindCalm ceiling fan.

The CLI reads device credentials from a ``.env`` file (or the environment)
instead of accepting them as arguments, so secrets never appear in shell
history or logs.

Usage examples::

    windcalm status
    windcalm on
    windcalm off
    windcalm speed 3
    windcalm direction reverse
    windcalm countdown 60
    windcalm light on
    windcalm scan
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import List, Optional

from .config import ConfigError, load_config
from .device import WindCalmDevice, WindCalmError
from .models import FanDirection, WorkMode
from .scanner import scan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="windcalm",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to a .env file (default: search for .env in cwd and parents)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Read the current fan status")
    sub.add_parser("scan", help="Scan for nearby BLE devices")

    on = sub.add_parser("on", help="Turn the fan on")
    on.add_argument("--speed", type=int, default=None, help="Fan speed (1-6)")

    sub.add_parser("off", help="Turn the fan off")

    speed = sub.add_parser("speed", help="Set the fan speed")
    speed.add_argument("value", type=int, help="Fan speed (1-6)")

    direction = sub.add_parser("direction", help="Set the fan rotation direction")
    direction.add_argument(
        "value",
        choices=["forward", "reverse"],
        help="Rotation direction",
    )

    countdown = sub.add_parser("countdown", help="Set the countdown timer")
    countdown.add_argument("value", type=int, help="Minutes (0-540)")

    light = sub.add_parser("light", help="Control the light")
    light.add_argument("value", choices=["on", "off"], help="Light state")

    mode = sub.add_parser("mode", help="Set the light work mode")
    mode.add_argument(
        "value",
        choices=["white", "colour", "scene", "music"],
        help="Light work mode",
    )

    return parser


async def _run_command(args: argparse.Namespace) -> int:
    if args.command == "scan":
        results = await scan()
        if not results:
            print("No BLE devices found.")
            return 0
        for result in results:
            print(f"{result.address}  {result.name}  {result.rssi} dBm")
        return 0

    config = load_config(args.env_file)
    async with WindCalmDevice(config) as fan:
        await fan.connect()

        if args.command == "status":
            status = await fan.get_status()
            print(status)
            return 0

        if args.command == "on":
            await fan.set_power(True)
            if args.speed is not None:
                await fan.set_speed(args.speed)
            print("Fan turned on.")
            return 0

        if args.command == "off":
            await fan.set_power(False)
            print("Fan turned off.")
            return 0

        if args.command == "speed":
            await fan.set_speed(args.value)
            print(f"Fan speed set to {args.value}.")
            return 0

        if args.command == "direction":
            direction = (
                FanDirection.FORWARD
                if args.value == "forward"
                else FanDirection.REVERSE
            )
            await fan.set_direction(direction)
            print(f"Fan direction set to {args.value}.")
            return 0

        if args.command == "countdown":
            await fan.set_countdown(args.value)
            print(f"Countdown set to {args.value} minutes.")
            return 0

        if args.command == "light":
            await fan.set_light(args.value == "on")
            print(f"Light turned {args.value}.")
            return 0

        if args.command == "mode":
            mode = {
                "white": WorkMode.WHITE,
                "colour": WorkMode.COLOUR,
                "scene": WorkMode.SCENE,
                "music": WorkMode.MUSIC,
            }[args.value]
            await fan.set_work_mode(mode)
            print(f"Light work mode set to {args.value}.")
            return 0

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        return asyncio.run(_run_command(args))
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except WindCalmError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())