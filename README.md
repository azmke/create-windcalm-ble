# create-windcalm-ble

Python library and CLI for controlling the **CREATE WIND CALM** ceiling fan
(and likely other Tuya ceiling fans) over **Bluetooth LE** - no WiFi, no Tuya Cloud.

## Features

- Pure BLE control (GATT), no network or cloud dependency.
- Reads the fan status (power, speed, direction, countdown, light).
- Controls power, speed, direction, countdown, light, and light work mode.
- Sensitive credentials are read from a `.env` file, never from CLI arguments.
- Async API built on `bleak`.

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
