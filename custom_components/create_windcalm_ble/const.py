"""Constants for the CREATE WindCalm BLE integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "create_windcalm_ble"

CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_UUID = "uuid"

DEFAULT_NAME = "WindCalm Ceiling Fan"
MANUFACTURER = "CREATE"
MODEL = "XW-FAN-215-D"
PRODUCT_ID = "p8z27dfdwc4riyp9"
CATEGORY = "fsd"

PLATFORMS = (Platform.FAN, Platform.LIGHT)
UPDATE_INTERVAL = timedelta(seconds=20)

EFFECT_WARM = "warm"
EFFECT_NEUTRAL = "neutral"
EFFECT_COLD = "cold"
LIGHT_EFFECTS = (EFFECT_WARM, EFFECT_NEUTRAL, EFFECT_COLD)

# The Tuya metadata only defines the 0..1000 range. These evenly spaced values
# are provisional until all three stages have been confirmed on real hardware.
LIGHT_EFFECT_TO_DP = {
    EFFECT_WARM: 0,
    EFFECT_NEUTRAL: 500,
    EFFECT_COLD: 1000,
}
