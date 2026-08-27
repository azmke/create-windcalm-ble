"""Tests for diagnostics redaction."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.create_windcalm_ble.const import DOMAIN
from custom_components.create_windcalm_ble.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_config_flow import USER_DATA


async def test_diagnostics_redact_all_credentials(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_DATA)
    coordinator = MagicMock()
    coordinator.device.is_connected = True
    coordinator.last_update_success = True
    coordinator.data = None
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    rendered = repr(diagnostics)
    for value in (
        USER_DATA["mac"],
        USER_DATA["device_id"],
        USER_DATA["uuid"],
        USER_DATA["local_key"],
    ):
        assert value not in rendered
