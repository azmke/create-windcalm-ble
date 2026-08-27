"""Fan entity for CREATE WindCalm BLE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import (
    DIRECTION_FORWARD,
    DIRECTION_REVERSE,
    FanEntity,
    FanEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from . import WindCalmConfigEntry
from .create_windcalm_ble import FanDirection
from .entity import WindCalmEntity

PARALLEL_UPDATES = 0
SPEEDS = ("1", "2", "3", "4", "5", "6")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WindCalmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the fan entity."""
    async_add_entities([WindCalmFan(entry.runtime_data.coordinator)])


class WindCalmFan(WindCalmEntity, FanEntity):
    """Representation of the ceiling fan motor."""

    _attr_name = None
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.DIRECTION
    )
    _attr_speed_count = 6

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "fan")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.power if self.coordinator.data else None

    @property
    def percentage(self) -> int | None:
        status = self.coordinator.data
        if status is None or status.speed is None:
            return None
        return ordered_list_item_to_percentage(SPEEDS, str(status.speed))

    @property
    def current_direction(self) -> str | None:
        status = self.coordinator.data
        if status is None or status.direction is None:
            return None
        if status.direction == FanDirection.FORWARD:
            return DIRECTION_FORWARD
        return DIRECTION_REVERSE

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        async def turn_on(device) -> None:
            await device.set_power(True)
            if percentage is not None:
                speed = int(percentage_to_ordered_list_item(SPEEDS, percentage))
                await device.set_speed(speed)

        await self.coordinator.async_execute(turn_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_execute(lambda device: device.set_power(False))

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = int(percentage_to_ordered_list_item(SPEEDS, percentage))
        await self.coordinator.async_execute(lambda device: device.set_speed(speed))

    async def async_set_direction(self, direction: str) -> None:
        fan_direction = (
            FanDirection.FORWARD
            if direction == DIRECTION_FORWARD
            else FanDirection.REVERSE
        )
        await self.coordinator.async_execute(
            lambda device: device.set_direction(fan_direction)
        )
