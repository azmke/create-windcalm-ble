"""Diagnostics support for CREATE WindCalm BLE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import WindCalmConfigEntry
from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY, CONF_UUID

TO_REDACT = {CONF_DEVICE_ID, CONF_LOCAL_KEY, CONF_UUID, "mac"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WindCalmConfigEntry
) -> dict[str, Any]:
    """Return credential-free diagnostics for one fan."""
    coordinator = entry.runtime_data.coordinator
    status = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "connected": coordinator.device.is_connected,
        "last_update_success": coordinator.last_update_success,
        "status": repr(status) if status is not None else None,
    }
