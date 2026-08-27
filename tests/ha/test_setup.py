"""Tests for config-entry setup, platforms, and unload."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.create_windcalm_ble.const import DOMAIN
from custom_components.create_windcalm_ble.create_windcalm_ble import FanStatus

from .test_config_flow import USER_DATA


async def test_setup_creates_fan_and_light_and_unloads(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=USER_DATA["name"],
        unique_id=USER_DATA["mac"],
        data=USER_DATA,
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.create_windcalm_ble.coordinator.WindCalmCoordinator._async_update_data",
        new=AsyncMock(return_value=FanStatus()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids("fan")) == 1
    assert len(hass.states.async_entity_ids("light")) == 1
    coordinator = entry.runtime_data.coordinator

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert coordinator.device.is_connected is False
