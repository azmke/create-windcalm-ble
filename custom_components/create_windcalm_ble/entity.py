"""Shared entity base for CREATE WindCalm BLE."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import WindCalmCoordinator


class WindCalmEntity(CoordinatorEntity[WindCalmCoordinator]):
    """Base entity attached to one ceiling fan device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WindCalmCoordinator, suffix: str) -> None:
        super().__init__(coordinator)
        mac = coordinator.config.mac
        self._attr_unique_id = f"{mac}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=coordinator.config.name,
        )
