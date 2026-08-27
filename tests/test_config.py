"""Tests for standalone configuration handling."""

import pytest

from create_windcalm_ble import Config, ConfigError


def test_config_hides_credentials_from_repr() -> None:
    config = Config(
        local_key="1234567890abcdef",
        device_id="device-id",
        uuid="device-uuid",
        mac="AA:BB:CC:DD:EE:FF",
    )

    rendered = repr(config)
    assert "1234567890abcdef" not in rendered
    assert "device-id" not in rendered
    assert "device-uuid" not in rendered
    assert "AA:BB:CC:DD:EE:FF" in rendered


@pytest.mark.parametrize(
    ("local_key", "device_id", "uuid"),
    [
        ("short", "device-id", "device-uuid"),
        ("123456", "", "device-uuid"),
        ("123456", "device-id", ""),
        ("123456", "x" * 30, "y" * 20),
        ("12345ü", "device-id", "device-uuid"),
    ],
)
def test_config_rejects_invalid_pairing_values(
    local_key: str, device_id: str, uuid: str
) -> None:
    with pytest.raises(ConfigError):
        Config(local_key, device_id, uuid, "AA:BB:CC:DD:EE:FF")
