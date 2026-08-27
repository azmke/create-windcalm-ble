# create-windcalm-ble

Python library and CLI for controlling the **CREATE WIND CALM** ceiling fan
(and likely other Tuya ceiling fans) over **Bluetooth LE** - no WiFi, no Tuya Cloud.

## Features

- Pure BLE control (GATT), no network or cloud dependency.
- Reads the fan status (power, speed, direction, countdown, light).
- Controls power, speed, direction, countdown, light, and light work mode.
- Exposes fan and light entities in Home Assistant, including three light
  temperature stages.
- Sensitive credentials are read from a `.env` file, never from CLI arguments.
- Async API built on `bleak`.

## Home Assistant / HACS

The repository also contains a native Home Assistant custom integration. It
uses Bluetooth directly; it does not require WiFi, a Tuya gateway, the Tuya
cloud, or a Home Assistant add-on.

### Requirements

- Home Assistant 2026.8 or newer.
- HACS 2.x for HACS installation.
- A connectable Bluetooth adapter or ESPHome Bluetooth proxy.
- MAC address, device ID, UUID, and local key for each fan.

### Installation through HACS

1. Add `https://github.com/azmke/create-windcalm-ble` to HACS as a custom
   repository of type **Integration**.
2. Install **CREATE WindCalm BLE** and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration** and select
   **CREATE WindCalm BLE**.
4. Enter one fan's name, MAC address, device ID, UUID, and local key. Repeat
   the flow for every additional fan.

Each fan creates a native fan entity (power, six speeds, direction) and a
light entity (power and warm/neutral/cold effects). The integration keeps one
BLE connection open per configured fan, so the Bluetooth adapter or proxies
must provide enough connection slots.

Credentials are stored in the Home Assistant config entry and are redacted
from diagnostics and logs. Home Assistant config entries are not an encrypted
secret vault: protect the HA host, its configuration directory, and backups.

The three light effects currently use the provisional raw DP values 0, 500,
and 1000. Verify these values with the physical fan before relying on the
labels; the Tuya metadata specifies only the range, not the three app stages.

## Requirements

- Python 3.9+
- Linux with a Bluetooth adapter (BlueZ). macOS/Windows may work but are not
  the primary target.

## Installation

Use the workspace virtual environment (do not install into the host Python):

```bash
cd create-windcalm-ble
.venv/bin/python -m pip install -e .
```

Or install the dependencies directly:

```bash
.venv/bin/python -m pip install bleak pycryptodome python-dotenv
```

## Configuration

Copy `.env.example` to `.env` and fill in your device values.

```dotenv
WIND_LOCAL_KEY=...
WIND_DEVICE_ID=...
WIND_UUID=...
WIND_MAC_ADDRESS=...
```

## CLI usage

```bash
# Read the current status
windcalm status

# Turn the fan on/off
windcalm on
windcalm off

# Set the speed (1-6)
windcalm speed 3

# Set the rotation direction
windcalm direction forward
windcalm direction reverse

# Set the countdown timer (minutes, 0-540)
windcalm countdown 60

# Control the light
windcalm light on
windcalm light off

# Set the raw light-temperature DP (0-1000)
windcalm light temperature 500

# Set the light work mode
windcalm mode white

# Scan for nearby BLE devices
windcalm scan
```

You can also run it as a module:

```bash
.venv/bin/python -m create_windcalm_ble status
```

## Library usage

```python
import asyncio
from create_windcalm_ble import Config, WindCalmDevice, load_config

async def main():
    config = load_config()  # reads .env
    async with WindCalmDevice(config) as fan:
        await fan.connect()
        status = await fan.get_status()
        print(status)
        await fan.set_speed(3)
        await fan.set_power(True)
        await fan.set_light_temperature(500)

asyncio.run(main())
```

## Protocol

The complete protocol description is in [PROTOCOL.md](docs/PROTOCOL.md), including transport
framing, encryption, authentication, pairing, acknowledgements, time
synchronization, datapoints, and connection lifetime behavior.

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for
the full license text.

## Disclaimer

See [DISCLAIMER.md](DISCLAIMER.md) for important information about permitted use, safety,
privacy, and compatibility limitations.
