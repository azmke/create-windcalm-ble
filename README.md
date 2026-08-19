# create-windcalm-ble

Python library for controlling the CREATE WIND CALM (and likely other Tuya ceiling fans) via Bluetooth LE

## Tools / Utils

### BLE Device Scanner

Scans once for nearby Bluetooth Low Energy devices and prints their name, address, and signal strength. The script exits after the scan; it does not connect to any device.

Run it with:

```bash
python3 tools/scan_ble_devices.py
```

The default sort order is RSSI, with the strongest signal first. Use `--sort` to choose another order.

## License

tbd

## Disclaimer

tbd