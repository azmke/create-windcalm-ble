"""Connection and state coordinator for CREATE WindCalm BLE."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .create_windcalm_ble import (
    Config,
    FanStatus,
    WindCalmAuthenticationError,
    WindCalmDevice,
    WindCalmError,
)

_LOGGER = logging.getLogger(__name__)


class WindCalmCoordinator(DataUpdateCoordinator[FanStatus]):
    """Maintain one persistent BLE session per configured fan."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: Config,
        entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{config.mac}",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.config = config
        self.entry = entry
        self._operation_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._stopping = False
        self.device = WindCalmDevice(
            config,
            client_factory=self._async_client_factory,
            status_callback=self._handle_status,
            disconnect_callback=self._handle_disconnect,
        )

    async def _async_client_factory(self, ble_device: Any, disconnected_callback):
        """Connect through HA's selected adapter or Bluetooth proxy."""
        return await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.config.name,
            disconnected_callback=disconnected_callback,
        )

    async def _async_ensure_connected(self) -> None:
        if self.device.is_connected:
            return
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.config.mac, connectable=True
        )
        if ble_device is None:
            raise WindCalmError("Device is not currently reachable over Bluetooth")
        self.device.set_ble_device(ble_device)
        await self.device.connect()

    async def _async_fetch(self) -> FanStatus:
        await self._async_ensure_connected()
        return await self.device.get_status()

    async def _async_update_data(self) -> FanStatus:
        try:
            async with self._operation_lock:
                return await self._async_fetch()
        except WindCalmAuthenticationError as exc:
            raise ConfigEntryAuthFailed("The fan rejected its credentials") from exc
        except WindCalmError as exc:
            raise UpdateFailed("Unable to communicate with the fan") from exc

    async def async_execute(
        self, action: Callable[[WindCalmDevice], Awaitable[None]]
    ) -> None:
        """Execute a control operation and publish the confirmed state."""
        try:
            async with self._operation_lock:
                await self._async_ensure_connected()
                await action(self.device)
                status = await self.device.get_status()
        except WindCalmAuthenticationError as exc:
            raise ConfigEntryAuthFailed("The fan rejected its credentials") from exc
        except WindCalmError as exc:
            raise HomeAssistantError("Unable to communicate with the fan") from exc
        self.async_set_updated_data(status)

    @callback
    def _handle_status(self, status: FanStatus) -> None:
        if not self._stopping:
            self.async_set_updated_data(status)

    @callback
    def _handle_disconnect(self) -> None:
        if self._stopping:
            return
        self.async_set_update_error(UpdateFailed("Bluetooth connection lost"))
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.hass.async_create_task(
                self._async_reconnect(), f"Reconnect {self.config.name}"
            )

    async def _async_reconnect(self) -> None:
        delay = 1
        while not self._stopping and not self.device.is_connected:
            await asyncio.sleep(delay)
            try:
                async with self._operation_lock:
                    status = await self._async_fetch()
            except WindCalmAuthenticationError:
                if self.entry is not None:
                    self.entry.async_start_reauth(self.hass)
                return
            except WindCalmError:
                delay = min(delay * 2, 60)
                continue
            self.async_set_updated_data(status)
            return

    async def async_shutdown(self) -> None:
        """Stop background work and disconnect cleanly."""
        self._stopping = True
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        await self.device.disconnect()


async def async_validate_connection(hass: HomeAssistant, config: Config) -> FanStatus:
    """Validate config-flow credentials without creating runtime state."""
    coordinator = WindCalmCoordinator(hass, config)
    try:
        return await coordinator._async_update_data()
    except UpdateFailed as exc:
        raise ConfigEntryNotReady("Unable to communicate with the fan") from exc
    finally:
        await coordinator.async_shutdown()
