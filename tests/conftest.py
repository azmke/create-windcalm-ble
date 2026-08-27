"""Test path setup for the bundled standalone package."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "custom_components" / "create_windcalm_ble"
sys.path.insert(0, str(PACKAGE_ROOT))
