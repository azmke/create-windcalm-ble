"""WindCalm BLE — control a CREATE WIND CALM ceiling fan over Bluetooth LE.

This package implements the Tuya BLE V2/V3 protocol used by the fan and
exposes a small, focused API plus a command-line interface. It does not
depend on Home Assistant, WiFi, or the Tuya cloud.
"""

from .config import Config, ConfigError, load_config
from .device import (
    WindCalmAuthenticationError,
    WindCalmDevice,
    WindCalmError,
    WindCalmProtocolError,
)
from .models import (
    DataPoint,
    DataPointType,
    DeviceInfo,
    FanDirection,
    FanState,
    FanStatus,
    WorkMode,
)

__all__ = [
    "Config",
    "ConfigError",
    "DataPoint",
    "DataPointType",
    "DeviceInfo",
    "FanDirection",
    "FanState",
    "FanStatus",
    "WindCalmDevice",
    "WindCalmAuthenticationError",
    "WindCalmError",
    "WindCalmProtocolError",
    "WorkMode",
    "load_config",
]

__version__ = "0.2.0"
