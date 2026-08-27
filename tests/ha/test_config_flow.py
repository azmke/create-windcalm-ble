"""Tests for the Home Assistant config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_MAC, CONF_NAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.create_windcalm_ble.const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_UUID,
    DOMAIN,
)

USER_DATA = {
    CONF_NAME: "Living room fan",
    CONF_MAC: "AA:BB:CC:DD:EE:FF",
    CONF_DEVICE_ID: "device-id",
    CONF_UUID: "device-uuid",
    CONF_LOCAL_KEY: "1234567890abcdef",
}


async def test_user_flow_creates_one_entry(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM

    with (
        patch(
            "custom_components.create_windcalm_ble.config_flow.bluetooth.async_scanner_count",
            return_value=1,
        ),
        patch(
            "custom_components.create_windcalm_ble.config_flow.async_validate_connection",
            new=AsyncMock(),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_DATA
        )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living room fan"
    assert result["data"] == USER_DATA
    assert result["result"].unique_id == "AA:BB:CC:DD:EE:FF"


async def test_user_flow_rejects_duplicate_mac(hass) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_DATA[CONF_MAC],
        data=USER_DATA,
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_DATA
    )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_reports_missing_adapter(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.create_windcalm_ble.config_flow.bluetooth.async_scanner_count",
        return_value=0,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_DATA
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "no_bluetooth_adapter"}
    assert USER_DATA[CONF_LOCAL_KEY] not in repr(result)


async def test_reconfigure_keeps_blank_local_key(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=USER_DATA[CONF_NAME],
        unique_id=USER_DATA[CONF_MAC],
        data=USER_DATA,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    changed = {
        CONF_NAME: "Bedroom fan",
        CONF_MAC: USER_DATA[CONF_MAC],
        CONF_DEVICE_ID: USER_DATA[CONF_DEVICE_ID],
        CONF_UUID: USER_DATA[CONF_UUID],
        CONF_LOCAL_KEY: "",
    }
    with (
        patch(
            "custom_components.create_windcalm_ble.config_flow.bluetooth.async_scanner_count",
            return_value=1,
        ),
        patch(
            "custom_components.create_windcalm_ble.config_flow.async_validate_connection",
            new=AsyncMock(),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], changed
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_LOCAL_KEY] == USER_DATA[CONF_LOCAL_KEY]
    assert entry.title == "Bedroom fan"


async def test_reauth_updates_credentials(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=USER_DATA[CONF_NAME],
        unique_id=USER_DATA[CONF_MAC],
        data=USER_DATA,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=dict(entry.data),
    )
    assert result["step_id"] == "reauth_confirm"

    replacement = {
        CONF_DEVICE_ID: USER_DATA[CONF_DEVICE_ID],
        CONF_UUID: USER_DATA[CONF_UUID],
        CONF_LOCAL_KEY: "fedcba0987654321",
    }
    with (
        patch(
            "custom_components.create_windcalm_ble.config_flow.bluetooth.async_scanner_count",
            return_value=1,
        ),
        patch(
            "custom_components.create_windcalm_ble.config_flow.async_validate_connection",
            new=AsyncMock(),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], replacement
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_LOCAL_KEY] == replacement[CONF_LOCAL_KEY]
