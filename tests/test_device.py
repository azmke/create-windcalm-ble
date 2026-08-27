"""Tests for WindCalm BLE device behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from create_windcalm_ble.device import (
    CMD_DEVICE_STATUS,
    CMD_SEND_DPS,
    DP_LIGHT_TEMPERATURE,
)
from create_windcalm_ble.models import DataPoint, DataPointType

from create_windcalm_ble import Config, FanStatus, WindCalmDevice


@pytest.fixture
def config() -> Config:
    return Config(
        local_key="1234567890abcdef",
        device_id="device-id",
        uuid="device-uuid",
        mac="AA:BB:CC:DD:EE:FF",
    )


def test_light_temperature_legacy_alias() -> None:
    status = FanStatus(light_temperature=500)
    assert status.temperature == 500
    status.temperature = 1000
    assert status.light_temperature == 1000


def test_set_light_temperature(config: Config) -> None:
    async def run() -> None:
        device = WindCalmDevice(config)
        device._set_datapoint = AsyncMock()  # type: ignore[method-assign]

        await device.set_light_temperature(500)

        device._set_datapoint.assert_awaited_once_with(  # type: ignore[attr-defined]
            DP_LIGHT_TEMPERATURE, DataPointType.VALUE, 500
        )
        with pytest.raises(ValueError):
            await device.set_light_temperature(1001)

    asyncio.run(run())


def test_get_status_waits_for_new_report(config: Config) -> None:
    async def run() -> None:
        device = WindCalmDevice(config)
        device._datapoints[DP_LIGHT_TEMPERATURE] = DataPoint(
            DP_LIGHT_TEMPERATURE, DataPointType.VALUE, 0
        )
        device._send_command_locked = AsyncMock(return_value=b"")  # type: ignore[method-assign]

        task = asyncio.create_task(device.get_status())
        await asyncio.sleep(0)
        assert not task.done()

        device._datapoints[DP_LIGHT_TEMPERATURE] = DataPoint(
            DP_LIGHT_TEMPERATURE, DataPointType.VALUE, 500
        )
        device._report_generation += 1
        device._report_event.set()

        status = await task
        assert status.light_temperature == 500
        device._send_command_locked.assert_awaited_once_with(  # type: ignore[attr-defined]
            CMD_DEVICE_STATUS, b""
        )

    asyncio.run(run())


def test_writes_do_not_interleave(config: Config) -> None:
    async def run() -> None:
        device = WindCalmDevice(config)
        client = AsyncMock()
        device._client = client
        device._connected = True

        def build_packets(
            code: int, payload: bytes, response_to: int = 0
        ) -> list[bytes]:
            sequence = device._tx_counter
            device._tx_counter += 1
            return [bytes((sequence, 1)), bytes((sequence, 2))]

        device._build_packets = build_packets  # type: ignore[method-assign]

        await asyncio.gather(
            device._write_command(CMD_SEND_DPS, b"a"),
            device._write_command(CMD_SEND_DPS, b"b"),
        )

        packets = [call.args[1] for call in client.write_gatt_char.await_args_list]
        assert packets in (
            [b"\x01\x01", b"\x01\x02", b"\x02\x01", b"\x02\x02"],
            [b"\x02\x01", b"\x02\x02", b"\x01\x01", b"\x01\x02"],
        )

    asyncio.run(run())
