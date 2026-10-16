"""Config flow for the Marantz AVR integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_SERIAL_URL,
    CONF_SOURCES,
    CONNECTION_NETWORK,
    CONNECTION_SERIAL,
    DEFAULT_NETWORK_PORT,
    DOMAIN,
    SOURCES,
)
from .protocol import MarantzClient, MarantzError, Opener, serial_opener, tcp_opener

_LOGGER = logging.getLogger(__name__)

NETWORK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_NETWORK_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)
SERIAL_SCHEMA = vol.Schema({vol.Required(CONF_SERIAL_URL): str})


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


async def validate_connection(opener: Opener) -> dict[str, str | None]:
    """Connect, check the receiver answers and return model information."""
    client = MarantzClient(opener, heartbeat_interval=3600)
    try:
        await client.start(timeout=15)
    except (MarantzError, OSError, ValueError) as err:
        raise CannotConnect from err
    info: dict[str, str | None] = {"model": None, "name": None}
    try:
        try:
            line = await client.request("SYMO", "SYMO", timeout=3)
            info["model"] = line[4:].strip() or None
        except (TimeoutError, MarantzError):
            pass
        try:
            line = await client.request("NSFRN ?", "NSFRN ", timeout=3)
            info["name"] = line[6:].strip() or None
        except (TimeoutError, MarantzError):
            pass
    finally:
        await client.stop()
    return info


def _title(info: dict[str, str | None]) -> str:
    if info.get("name"):
        return str(info["name"])
    if info.get("model"):
        return f"Marantz {info['model']}"
    return "Marantz AVR"


def _opener_for(connection_type: str, data: dict[str, Any]) -> Opener:
    if connection_type == CONNECTION_SERIAL:
        return serial_opener(data[CONF_SERIAL_URL])
    return tcp_opener(data[CONF_HOST], data[CONF_PORT])


def _unique_id(connection_type: str, data: dict[str, Any]) -> str:
    if connection_type == CONNECTION_SERIAL:
        return f"serial:{data[CONF_SERIAL_URL]}"
    return f"network:{data[CONF_HOST]}:{data[CONF_PORT]}"


class MarantzConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return MarantzOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how the receiver is connected."""
        return self.async_show_menu(
            step_id="user", menu_options=[CONNECTION_NETWORK, CONNECTION_SERIAL]
        )

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a telnet (IP) connection."""
        return await self._async_step_connection(
            CONNECTION_NETWORK, NETWORK_SCHEMA, user_input
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an RS-232C connection (local port or serial server)."""
        return await self._async_step_connection(
            CONNECTION_SERIAL, SERIAL_SCHEMA, user_input
        )

    async def _async_step_connection(
        self,
        connection_type: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reconfigure = self.source == "reconfigure"
        if user_input is not None:
            if connection_type == CONNECTION_SERIAL:
                user_input[CONF_SERIAL_URL] = user_input[CONF_SERIAL_URL].strip()
            else:
                user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            unique_id = _unique_id(connection_type, user_input)
            if reconfigure:
                if self._unique_id_in_use_by_other(unique_id):
                    return self.async_abort(reason="already_configured")
            else:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
            try:
                info = await validate_connection(
                    _opener_for(connection_type, user_input)
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_url"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                data = {CONF_CONNECTION_TYPE: connection_type, **user_input}
                if reconfigure:
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(),
                        unique_id=unique_id,
                        data=data,
                    )
                return self.async_create_entry(title=_title(info), data=data)

        suggested = user_input
        if suggested is None and reconfigure:
            suggested = dict(self._get_reconfigure_entry().data)
        return self.async_show_form(
            step_id=connection_type,
            data_schema=self.add_suggested_values_to_schema(schema, suggested or {}),
            errors=errors,
        )

    def _unique_id_in_use_by_other(self, unique_id: str) -> bool:
        """Return True if another entry already uses this connection."""
        entry = self._get_reconfigure_entry()
        return any(
            other.entry_id != entry.entry_id and other.unique_id == unique_id
            for other in self._async_current_entries(include_ignore=False)
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the connection settings."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=[CONNECTION_NETWORK, CONNECTION_SERIAL],
        )


class MarantzOptionsFlow(OptionsFlow):
    """Options: which input sources to show."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        device = getattr(self.config_entry, "runtime_data", None)
        if device is not None:
            default = device.enabled_sources()
            names = {code: device.source_name(code) for code in SOURCES}
        else:
            default = list(SOURCES)
            names = dict(SOURCES)
        options = [
            selector.SelectOptionDict(
                value=code,
                label=names[code] if names[code] == code else f"{names[code]} ({code})",
            )
            for code in SOURCES
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOURCES,
                    default=self.config_entry.options.get(CONF_SOURCES, default),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
