"""Fixtures for Home Assistant integration tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading this repository's custom integration."""
    yield
