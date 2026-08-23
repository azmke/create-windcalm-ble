"""Data models for the WindCalm BLE device.

These types describe the Tuya datapoints (DPs) exposed by the fan and the
high-level fan state derived from them. They are protocol-agnostic so that
callers do not need to know about the wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, Optional


class DataPointType(IntEnum):
    """Tuya datapoint value types."""

    RAW = 0
    BOOL = 1
    VALUE = 2
    STRING = 3
    ENUM = 4
    BITMAP = 5


class FanState(IntEnum):
    """Fan power state (DP 60)."""

    OFF = 0
    ON = 1


class FanDirection(IntEnum):
    """Fan rotation direction (DP 63)."""

    FORWARD = 0
    REVERSE = 1


class WorkMode(IntEnum):
    """Light work mode (DP 21)."""

    WHITE = 0
    COLOUR = 1
    SCENE = 2
    MUSIC = 3


@dataclass
class DataPoint:
    """A single Tuya datapoint with its decoded value."""

    id: int
    type: DataPointType
    value: Any
    timestamp: float = 0.0

    def __repr__(self) -> str:
        return f"DataPoint(id={self.id}, type={self.type.name}, value={self.value!r})"


@dataclass
class DeviceInfo:
    """Decoded device information returned by the device-info exchange."""

    protocol_version: int
    flags: int
    is_bound: bool
    srand: bytes
    auth_key: bytes
    raw: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "DeviceInfo":
        """Parse a device-info reply into a :class:`DeviceInfo`.

        The reply layout (from the Tuya BLE V2/V3 protocol, matching
        ``ha_tuya_ble``) is::

            offset 0   : device version (2 bytes)
            offset 2   : protocol version (2 bytes)
            offset 4   : flags (1 byte)
            offset 5   : bound state (1 byte)
            offset 6   : srand, 6 bytes
            offset 12  : hardware version (2 bytes)
            offset 14  : auth key, 32 bytes

        Parameters
        ----------
        data:
            The raw device-info payload.

        Returns
        -------
        DeviceInfo
            The parsed device information.
        """
        if len(data) < 46:
            raise ValueError("Device-info reply is too short")
        return cls(
            protocol_version=data[2],
            flags=data[4],
            is_bound=bool(data[5]),
            srand=data[6:12],
            auth_key=data[14:46],
            raw=data,
        )


@dataclass
class FanStatus:
    """High-level status of the fan, decoded from its datapoints."""

    power: Optional[bool] = None
    speed: Optional[int] = None
    direction: Optional[FanDirection] = None
    countdown: Optional[int] = None
    light_on: Optional[bool] = None
    work_mode: Optional[WorkMode] = None
    temperature: Optional[int] = None
    datapoints: Dict[int, DataPoint] = field(default_factory=dict)

    def __repr__(self) -> str:
        parts = [
            f"power={self.power}",
            f"speed={self.speed}",
            f"direction={self.direction.name if self.direction is not None else None}",
            f"countdown={self.countdown}",
            f"light_on={self.light_on}",
            f"work_mode={self.work_mode.name if self.work_mode is not None else None}",
            f"temperature={self.temperature}",
        ]
        return f"FanStatus({', '.join(parts)})"