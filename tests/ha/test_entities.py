"""Tests for native Home Assistant entity mappings."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.fan import DIRECTION_FORWARD

from custom_components.create_windcalm_ble.const import EFFECT_COLD
from custom_components.create_windcalm_ble.create_windcalm_ble import (
    Config,
    FanDirection,
    FanStatus,
    WorkMode,
)
from custom_components.create_windcalm_ble.fan import WindCalmFan
from custom_components.create_windcalm_ble.light import WindCalmLight


def coordinator(status: FanStatus):
    result = MagicMock()
    result.config = Config(
        "1234567890abcdef",
        "device-id",
        "device-uuid",
        "AA:BB:CC:DD:EE:FF",
    )
    result.data = status
    result.last_update_success = True
    return result


async def test_fan_maps_six_speeds_and_direction() -> None:
    coord = coordinator(FanStatus(power=True, speed=3, direction=FanDirection.FORWARD))
    entity = WindCalmFan(coord)
    device = AsyncMock()

    async def execute(action):
        await action(device)

    coord.async_execute = AsyncMock(side_effect=execute)

    assert entity.is_on is True
    assert entity.percentage == 50
    assert entity.current_direction == DIRECTION_FORWARD

    await entity.async_set_percentage(100)
    device.set_speed.assert_awaited_once_with(6)


async def test_light_maps_effect_to_work_mode_and_dp() -> None:
    coord = coordinator(
        FanStatus(
            light_on=True,
            light_temperature=1000,
            work_mode=WorkMode.WHITE,
        )
    )
    entity = WindCalmLight(coord)
    device = AsyncMock()

    async def execute(action):
        await action(device)

    coord.async_execute = AsyncMock(side_effect=execute)

    assert entity.is_on is True
    assert entity.effect == EFFECT_COLD

    await entity.async_turn_on(effect=EFFECT_COLD)
    device.set_work_mode.assert_awaited_once_with(WorkMode.WHITE)
    device.set_light_temperature.assert_awaited_once_with(1000)
    device.set_light.assert_awaited_once_with(True)
