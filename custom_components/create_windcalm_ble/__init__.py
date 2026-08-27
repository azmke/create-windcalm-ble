"""CREATE WindCalm BLE Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant

from .const import (
    CATEGORY,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_UUID,
    PLATFORMS,
    PRODUCT_ID,
)
from .coordinator import WindCalmCoordinator
from .create_windcalm_ble import Config


@dataclass
class WindCalmRuntimeData:
    """Runtime objects owned by one config entry."""

    coordinator: WindCalmCoordinator


WindCalmConfigEntry = ConfigEntry[WindCalmRuntimeData]


def config_from_entry(entry: ConfigEntry) -> Config:
    """Build the standalone library config from HA storage."""
    return Config(
        local_key=entry.data[CONF_LOCAL_KEY],
        device_id=entry.data[CONF_DEVICE_ID],
        uuid=entry.data[CONF_UUID],
        mac=entry.data[CONF_MAC],
        product_id=PRODUCT_ID,
        category=CATEGORY,
        name=entry.data[CONF_NAME],
    )


async def async_setup_entry(hass: HomeAssistant, entry: WindCalmConfigEntry) -> bool:
    """Set up one configured ceiling fan."""
    coordinator = WindCalmCoordinator(hass, config_from_entry(entry), entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = WindCalmRuntimeData(coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WindCalmConfigEntry) -> bool:
    """Unload one configured ceiling fan."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.async_shutdown()
    return True
