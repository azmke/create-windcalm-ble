"""UI configuration flow for CREATE WindCalm BLE."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CATEGORY,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_UUID,
    DEFAULT_NAME,
    DOMAIN,
    PRODUCT_ID,
)
from .coordinator import async_validate_connection
from .create_windcalm_ble import Config, ConfigError

TEXT = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
PASSWORD = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="off")
)


def _normalize_mac(value: str) -> str:
    """Normalize and validate a Bluetooth MAC address."""
    mac = format_mac(value).upper()
    if len(mac) != 17 or any(len(part) != 2 for part in mac.split(":")):
        raise ValueError("Invalid MAC address")
    return mac


def _config(data: dict[str, Any]) -> Config:
    return Config(
        local_key=data[CONF_LOCAL_KEY],
        device_id=data[CONF_DEVICE_ID],
        uuid=data[CONF_UUID],
        mac=data[CONF_MAC],
        product_id=PRODUCT_ID,
        category=CATEGORY,
        name=data[CONF_NAME],
    )


def _user_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=DEFAULT_NAME): TEXT,
            vol.Required(CONF_MAC): TEXT,
            vol.Required(CONF_DEVICE_ID): TEXT,
            vol.Required(CONF_UUID): TEXT,
            vol.Required(CONF_LOCAL_KEY): PASSWORD,
        }
    )


class WindCalmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one ceiling fan per config entry."""

    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, str]:
        try:
            data[CONF_MAC] = _normalize_mac(data[CONF_MAC])
            config = _config(data)
        except (ConfigError, ValueError):
            return {"base": "invalid_input"}
        if bluetooth.async_scanner_count(self.hass, connectable=True) == 0:
            return {"base": "no_bluetooth_adapter"}
        try:
            status = await async_validate_connection(self.hass, config)
        except ConfigEntryAuthFailed:
            return {"base": "invalid_auth"}
        except ConfigEntryNotReady:
            return {"base": "cannot_connect"}
        if status.power is None and status.light_on is None:
            return {"base": "unsupported_device"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input[CONF_MAC] = _normalize_mac(user_input[CONF_MAC])
            except ValueError:
                errors = {"base": "invalid_input"}
            else:
                await self.async_set_unique_id(user_input[CONF_MAC])
                self._abort_if_unique_id_configured()
                errors = await self._async_validate(user_input)
                if not errors:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME], data=user_input
                    )
        suggested = dict(user_input or {})
        suggested.pop(CONF_LOCAL_KEY, None)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_user_schema(), suggested),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(entry.data)
            data.update(user_input)
            if not user_input.get(CONF_LOCAL_KEY):
                data[CONF_LOCAL_KEY] = entry.data[CONF_LOCAL_KEY]
            data[CONF_MAC] = entry.data[CONF_MAC]
            await self.async_set_unique_id(data[CONF_MAC])
            self._abort_if_unique_id_mismatch()
            errors = await self._async_validate(data)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, title=data[CONF_NAME], data=data
                )
        suggested = dict(entry.data)
        suggested.pop(CONF_LOCAL_KEY, None)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TEXT,
                vol.Required(CONF_MAC): TextSelector(
                    TextSelectorConfig(read_only=True)
                ),
                vol.Required(CONF_DEVICE_ID): TEXT,
                vol.Required(CONF_UUID): TEXT,
                vol.Optional(CONF_LOCAL_KEY): PASSWORD,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(entry.data)
            data.update(user_input)
            errors = await self._async_validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): TEXT,
                vol.Required(CONF_UUID): TEXT,
                vol.Required(CONF_LOCAL_KEY): PASSWORD,
            }
        )
        suggested = {
            CONF_DEVICE_ID: entry.data[CONF_DEVICE_ID],
            CONF_UUID: entry.data[CONF_UUID],
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )
