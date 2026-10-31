"""Config flow: find the controller (auto-discovery or IP address), ask for its PIN, test it."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .client import FlameBossClient
from .const import CONF_DEVICE_ID, CONF_PIN, DEFAULT_PORT, DOMAIN

try:  # HA 2025.2+
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # older HA
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

_LOGGER = logging.getLogger(__name__)

_ID_FROM_NAME = re.compile(r"fb-(\d+)", re.IGNORECASE)


async def _probe(hass, data: dict[str, Any]) -> tuple[int | None, str | None]:
    """Connect once. Returns (device_id, error_key)."""
    client = FlameBossClient(
        hass.loop,
        data[CONF_HOST],
        data.get(CONF_PORT, DEFAULT_PORT),
        pin=data.get(CONF_PIN),
        device_id=data.get(CONF_DEVICE_ID),
    )
    client.start()
    try:
        if not await client.wait_connected(15):
            _LOGGER.debug("Flame Boss probe failed: %s", client.last_error)
            return None, "invalid_auth" if client.auth_failed else "cannot_connect"
        return await client.wait_for_device_id(8), None
    finally:
        await client.stop()


class FlameBossConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id, error = await _probe(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                return await self._create(user_input, device_id)

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_PIN, default=defaults.get(CONF_PIN, "")): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        name = f"{discovery_info.hostname} {discovery_info.name}"
        match = _ID_FROM_NAME.search(name)
        device_id = int(match.group(1)) if match else None
        host = str(discovery_info.ip_address)
        port = discovery_info.port or DEFAULT_PORT
        if device_id is not None:
            await self.async_set_unique_id(str(device_id))
            self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
        self._async_abort_entries_match({CONF_HOST: host})
        self._discovered = {CONF_HOST: host, CONF_PORT: port, CONF_DEVICE_ID: device_id}
        self.context["title_placeholders"] = {"name": f"Flame Boss {device_id or host}"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._discovered, CONF_PIN: user_input[CONF_PIN]}
            device_id, error = await _probe(self.hass, data)
            if error:
                errors["base"] = error
            else:
                return await self._create(data, device_id or self._discovered.get(CONF_DEVICE_ID))
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            description_placeholders={"host": self._discovered[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new PIN (e.g. after the controller was reset)."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PIN: user_input[CONF_PIN]}
            _, error = await _probe(self.hass, data)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the IP address or PIN."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            _, error = await _probe(self.hass, data)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                vol.Required(CONF_PIN, default=entry.data.get(CONF_PIN, "")): str,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    async def _create(self, data: dict[str, Any], device_id: int | None) -> ConfigFlowResult:
        await self.async_set_unique_id(str(device_id) if device_id else data[CONF_HOST])
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: data[CONF_HOST], CONF_PIN: data[CONF_PIN]}
        )
        entry_data = {k: v for k, v in data.items() if v not in (None, "")}
        if device_id:
            entry_data[CONF_DEVICE_ID] = device_id
        title = f"Flame Boss {device_id}" if device_id else f"Flame Boss ({data[CONF_HOST]})"
        return self.async_create_entry(title=title, data=entry_data)
