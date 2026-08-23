#!/usr/bin/env python3
"""Scan once for nearby Bluetooth Low Energy devices."""

from __future__ import annotations

import asyncio
import argparse
import sys
from typing import Any


SCAN_TIMEOUT = 5.0


async def scan_devices(sort_by: str = "rssi") -> int:
	"""Scan for nearby devices, print a compact list, and return an exit code."""
	try:
		from bleak import BleakScanner
	except ImportError:
		print("Missing dependency: install it with 'python -m pip install bleak'.")
		return 2

	print(f"Scanning for BLE devices for {SCAN_TIMEOUT:.0f} seconds...", flush=True)
	try:
		result = await asyncio.wait_for(
			BleakScanner.discover(
				timeout=SCAN_TIMEOUT,
				return_adv=True,
			),
			timeout=SCAN_TIMEOUT + 2.0,
		)
	except asyncio.TimeoutError:
		print("Scan timed out.", file=sys.stderr)
		return 1
	except Exception as exc:  # BLE backends expose platform-specific errors.
		print(f"Scan failed: {format_error(exc)}", file=sys.stderr)
		return 1

	devices = sorted(
		normalize_result(result),
		key=sort_key(sort_by),
		reverse=sort_by == "rssi",
	)
	if not devices:
		print("No BLE devices found.")
		return 0

	print(f"Found {len(devices)} BLE device(s):")
	print(f"{'Name':<32} {'Address':<20} {'RSSI':>8}")
	print("-" * 64)
	for device, advertisement in devices:
		name = device_name(device, advertisement)
		rssi = device_rssi(device, advertisement)
		print(f"{name[:32]:<32} {device_address(device):<20} {rssi:>8}")

	return 0


def normalize_result(result: Any) -> list[tuple[Any, Any | None]]:
	"""Normalize Bleak's return_adv dictionary and older list result formats."""
	values = result.values() if isinstance(result, dict) else result
	devices: list[tuple[Any, Any | None]] = []
	for value in values:
		if isinstance(value, tuple) and len(value) == 2:
			devices.append((value[0], value[1]))
		else:
			devices.append((value, None))
	return devices


def device_name(device: Any, advertisement: Any | None) -> str:
	"""Return the advertised name, falling back to the backend device name."""
	return str(
		getattr(device, "name", None)
		or getattr(advertisement, "local_name", None)
		or "Unknown device"
	)


def device_address(device: Any) -> str:
	"""Return the platform-specific device address."""
	return str(getattr(device, "address", "unknown"))


def device_rssi(device: Any, advertisement: Any | None) -> str:
	"""Return the signal strength when supplied by the scanner backend."""
	rssi = getattr(advertisement, "rssi", None)
	if rssi is None:
		rssi = getattr(device, "rssi", None)
	return f"{rssi} dBm" if rssi is not None else "n/a"


def rssi_value(device: Any, advertisement: Any | None) -> int:
	"""Return RSSI as a sortable value, putting unavailable values last."""
	rssi = getattr(advertisement, "rssi", None)
	if rssi is None:
		rssi = getattr(device, "rssi", None)
	return int(rssi) if rssi is not None else -1000


def sort_key(sort_by: str):
	"""Return the sort key requested by the command line."""
	if sort_by == "name":
		return lambda item: (device_name(*item).lower(), device_address(item[0]).lower())
	if sort_by == "address":
		return lambda item: device_address(item[0]).lower()
	return lambda item: (rssi_value(*item), device_address(item[0]).lower())


def format_error(error: Exception) -> str:
	"""Keep backend-specific exceptions readable in the terminal."""
	message = str(error).strip().replace("\n", " ")
	return message or error.__class__.__name__


def main() -> int:
	"""Run one scan and exit."""
	parser = argparse.ArgumentParser(
		description="Scan once for nearby Bluetooth Low Energy devices."
	)
	parser.add_argument(
		"--sort",
		choices=("name", "address", "rssi"),
		default="rssi",
		help="sort devices by name, address, or signal strength (default: rssi)",
	)
	args = parser.parse_args()

	try:
		return asyncio.run(scan_devices(args.sort))
	except KeyboardInterrupt:
		print("\nScan cancelled.", file=sys.stderr)
		return 130


if __name__ == "__main__":
	raise SystemExit(main())
