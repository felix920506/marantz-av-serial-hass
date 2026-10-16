"""Config flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.marantz_avr.const import (
    CONF_CONNECTION_TYPE,
    CONF_SERIAL_URL,
    CONF_SOURCES,
    CONNECTION_NETWORK,
    CONNECTION_SERIAL,
    DOMAIN,
)

from .fake_receiver import FakeReceiver


async def test_network_flow(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": CONNECTION_NETWORK}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: receiver.port}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Marantz CINEMA 40"
    assert result["data"] == {
        CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
        CONF_HOST: "127.0.0.1",
        CONF_PORT: receiver.port,
    }
    await hass.async_block_till_done()

    # Same connection again -> aborted.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": CONNECTION_NETWORK}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: receiver.port}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_serial_flow(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": CONNECTION_SERIAL}
    )
    url = f"socket://127.0.0.1:{receiver.port}"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SERIAL_URL: f" {url} "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
        CONF_SERIAL_URL: url,
    }
    await hass.async_block_till_done()
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_flow_errors(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": CONNECTION_SERIAL}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SERIAL_URL: "socket://bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}

    receiver.mute_responses = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SERIAL_URL: f"socket://127.0.0.1:{receiver.port}"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="network:10.0.0.1:23",
        data={
            CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
            CONF_HOST: "10.0.0.1",
            CONF_PORT: 23,
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": CONNECTION_SERIAL}
    )
    url = f"socket://127.0.0.1:{receiver.port}"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SERIAL_URL: url}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_CONNECTION_TYPE: CONNECTION_SERIAL, CONF_SERIAL_URL: url}
    assert entry.unique_id == f"serial:{url}"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow(hass: HomeAssistant, receiver: FakeReceiver) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
            CONF_HOST: "127.0.0.1",
            CONF_PORT: receiver.port,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SOURCES: ["CD", "NET"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    state = hass.states.get("media_player.mock_title")
    assert state.attributes["source_list"] == ["CD", "HEOS Music"]
    await hass.config_entries.async_unload(entry.entry_id)
