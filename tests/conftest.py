"""Fixtures for Marantz AVR tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from .fake_receiver import FakeReceiver


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


@pytest.fixture
async def receiver(socket_enabled) -> AsyncGenerator[FakeReceiver]:
    """Start a fake receiver."""
    fake = FakeReceiver()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture(autouse=True)
def fast_command_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speed up tests by shortening the inter-command delay."""
    from custom_components.marantz_avr import protocol

    monkeypatch.setattr(protocol, "COMMAND_INTERVAL", 0.002)
    monkeypatch.setattr(protocol, "POWER_ON_DELAY", 0.01)
