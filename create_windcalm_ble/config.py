"""Configuration loading for the WindCalm BLE package.

Sensitive device credentials (local key, device id, UUID, MAC address) are
read from a ``.env`` file or the process environment instead of being passed
as command-line arguments. This keeps secrets out of shell history and logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when the device configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Credentials and addressing information for a single WindCalm fan."""

    local_key: str
    device_id: str
    uuid: str
    mac: str
    product_id: str = "p8z27dfdwc4riyp9"
    category: str = "fsd"
    name: str = "WindCalm Ceiling Fan"

    @property
    def login_key(self) -> bytes:
        """Return the 6-byte login key derived from the local key.

        The login key is the first six bytes of the local key, used to
        encrypt the initial device-info exchange.
        """
        return self.local_key[:6].encode("ascii")


def _require(name: str, value: Optional[str]) -> str:
    """Return a non-empty environment value or raise :class:`ConfigError`."""
    if not value:
        raise ConfigError(
            f"Missing configuration value '{name}'. "
            "Set it in the environment or in a .env file."
        )
    return value


def load_config(
    env_file: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Config:
    """Load and validate the device configuration.

    Parameters
    ----------
    env_file:
        Optional path to a ``.env`` file. If omitted, the current working
        directory and its parents are searched for a ``.env`` file.
    env:
        Optional mapping used instead of ``os.environ``. Intended for tests.

    Returns
    -------
    Config
        A validated configuration object.

    Raises
    ------
    ConfigError
        If a required value is missing.
    """
    if env_file is not None:
        load_dotenv(env_file)
    else:
        load_dotenv()

    source = env if env is not None else os.environ

    return Config(
        local_key=_require("WIND_LOCAL_KEY", source.get("WIND_LOCAL_KEY")),
        device_id=_require("WIND_DEVICE_ID", source.get("WIND_DEVICE_ID")),
        uuid=_require("WIND_UUID", source.get("WIND_UUID")),
        mac=_require("WIND_MAC_ADDRESS", source.get("WIND_MAC_ADDRESS")),
        product_id=source.get("WIND_PRODUCT_ID", "p8z27dfdwc4riyp9"),
        category=source.get("WIND_CATEGORY", "fsd"),
        name=source.get("WIND_NAME", "WindCalm Ceiling Fan"),
    )