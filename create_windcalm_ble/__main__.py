"""Allow running the package as ``python -m create_windcalm_ble``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())