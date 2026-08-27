"""Light entity for CREATE WindCalm BLE."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WindCalmConfigEntry
from .const import LIGHT_EFFECT_TO_DP, LIGHT_EFFECTS
from .create_windcalm_ble import WorkMode
from .entity import WindCalmEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WindCalmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the light entity."""
    async_add_entities([WindCalmLight(entry.runtime_data.coordinator)])


class WindCalmLight(WindCalmEntity, LightEntity):
    """Representation of the integrated ceiling light."""

    _attr_translation_key = "light"
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list: ClassVar[list[str]] = list(LIGHT_EFFECTS)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "light")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.light_on if self.coordinator.data else None

    @property
    def effect(self) -> str | None:
        status = self.coordinator.data
        if (
            status is None
            or status.light_temperature is None
            or status.work_mode not in (None, WorkMode.WHITE)
        ):
            return None
        return min(
            LIGHT_EFFECT_TO_DP,
            key=lambda effect: abs(
                LIGHT_EFFECT_TO_DP[effect] - status.light_temperature
            ),
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        effect = kwargs.get(ATTR_EFFECT)

        async def turn_on(device) -> None:
            if effect is not None:
                await device.set_work_mode(WorkMode.WHITE)
                await device.set_light_temperature(LIGHT_EFFECT_TO_DP[effect])
            await device.set_light(True)

        await self.coordinator.async_execute(turn_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_execute(lambda device: device.set_light(False))
