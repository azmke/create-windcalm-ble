"""Bluetooth Low Energy scanning helpers.

These functions discover nearby Tuya BLE devices and match them against a
configured MAC address. They are thin wrappers around ``bleak``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from bleak import BleakScanner


@dataclass
class ScanResult:
    """A discovered BLE device."""

    address: str
    name: str
    rssi: Optional[int]

    def __repr__(self) -> str:
        return (
            f"ScanResult(address={self.address!r}, name={self.name!r}, "
            f"rssi={self.rssi})"
        )


async def scan(timeout: float = 5.0) -> List[ScanResult]:
    """Scan for nearby BLE devices.

    Parameters
    ----------
    timeout:
        Scan duration in seconds.

    Returns
    -------
    List[ScanResult]
        Discovered devices, strongest signal first.
    """
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = [
        ScanResult(
            address=device.address,
            name=device.name or "",
            rssi=advertisement_data.rssi,
        )
        for device, advertisement_data in devices.values()
    ]
    results.sort(key=lambda r: r.rssi if r.rssi is not None else -100, reverse=True)
    return results


async def find_device(mac: str, timeout: float = 5.0) -> Optional[ScanResult]:
    """Find a device by MAC address.

    Parameters
    ----------
    mac:
        MAC address to look for (case-insensitive, with or without colons).
    timeout:
        Scan duration in seconds.

    Returns
    -------
    Optional[ScanResult]
        The matching device, or ``None`` if it was not found.
    """
    target = mac.replace(":", "").upper()
    for result in await scan(timeout=timeout):
        if result.address.replace(":", "").upper() == target:
            return result
    return None
