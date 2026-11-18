"""Config flow: portal credentials + EAN, validated by a real login."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback

from .api import PortalClient, PortalError
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_EAN,
    CONF_HDO_COMMAND,
    CONF_HDO_HISTORY_DAYS,
    CONF_PRICE_NT,
    CONF_PRICE_VT,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_HDO_HISTORY_DAYS,
    DOMAIN,
    MAX_BACKFILL_DAYS,
    MAX_HDO_HISTORY_DAYS,
    get_hdo_command,
    get_price,
)
from .hdo import HdoError, HdoNoDataError, download_schedule_html


async def _async_validate_login(
    hass: HomeAssistant, username: str, password: str
) -> str | None:
    """Return an error key, or None if the login works."""
    try:
        await hass.async_add_executor_job(PortalClient().login, username, password)
    except PortalError:
        return "invalid_auth"
    except requests.RequestException:
        return "cannot_connect"
    return None


async def _async_validate_hdo(hass: HomeAssistant, command: str) -> str | None:
    """Return an error key, or None if the portal knows this command code."""
    if not command.isdigit():
        return "invalid_hdo_command"
    try:
        await hass.async_add_executor_job(download_schedule_html, command)
    except HdoNoDataError:
        return "unknown_hdo_command"
    except (HdoError, requests.RequestException):
        return "cannot_connect"
    return None


class PortalConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "PortalOptionsFlow":
        return PortalOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            ean = user_input[CONF_EAN].strip()
            # A cleared optional field is simply absent from user_input.
            hdo_command = user_input.get(CONF_HDO_COMMAND, "").strip()
            await self.async_set_unique_id(ean)
            self._abort_if_unique_id_configured()
            error = await _async_validate_login(
                self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if error is None and hdo_command:
                error = await _async_validate_hdo(self.hass, hdo_command)
            if error is None:
                data = {**user_input, CONF_EAN: ean}
                data.pop(CONF_HDO_COMMAND, None)
                if hdo_command:
                    data[CONF_HDO_COMMAND] = hdo_command
                return self.async_create_entry(
                    title=f"PREdistribuce {ean}", data=data
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_EAN): str,
                vol.Required(CONF_BACKFILL_DAYS, default=DEFAULT_BACKFILL_DAYS): vol.All(
                    int, vol.Range(min=1, max=MAX_BACKFILL_DAYS)
                ),
                vol.Optional(CONF_HDO_COMMAND): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            error = await _async_validate_login(
                self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )


class PortalOptionsFlow(OptionsFlowWithReload):
    """Add, change or remove the HDO command code after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # A cleared field is absent from user_input -> HDO disabled.
            command = user_input.get(CONF_HDO_COMMAND, "").strip()
            error = await _async_validate_hdo(self.hass, command) if command else None
            if error is None:
                # "" (not a missing key) so it overrides the value in entry.data.
                return self.async_create_entry(
                    data={
                        CONF_HDO_COMMAND: command,
                        CONF_HDO_HISTORY_DAYS: user_input.get(
                            CONF_HDO_HISTORY_DAYS, DEFAULT_HDO_HISTORY_DAYS
                        ),
                        # 0 = no cost statistic (a cleared field is absent).
                        CONF_PRICE_NT: user_input.get(CONF_PRICE_NT, 0),
                        CONF_PRICE_VT: user_input.get(CONF_PRICE_VT, 0),
                    }
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_HDO_COMMAND,
                    description={"suggested_value": get_hdo_command(self.config_entry)},
                ): str,
                vol.Optional(
                    CONF_HDO_HISTORY_DAYS,
                    default=self.config_entry.options.get(
                        CONF_HDO_HISTORY_DAYS, DEFAULT_HDO_HISTORY_DAYS
                    ),
                ): vol.All(int, vol.Range(min=1, max=MAX_HDO_HISTORY_DAYS)),
                vol.Optional(
                    CONF_PRICE_NT,
                    description={
                        "suggested_value": get_price(self.config_entry, CONF_PRICE_NT)
                    },
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                vol.Optional(
                    CONF_PRICE_VT,
                    description={
                        "suggested_value": get_price(self.config_entry, CONF_PRICE_VT)
                    },
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
