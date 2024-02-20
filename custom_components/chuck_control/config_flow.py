"""Config flow for Chuck Charger Control integration."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

import logging
from typing import Any
import voluptuous as vol

from .chuck_rest import ChuckChargeBox, ChuckAuthError, ChuckRestError, ChuckRestTimeout
from .const import (
    DOMAIN,
    PHASE_ORDER_DICT,
    PHASE_ORDER_DICT_DEFAULT_CFG,
    CONF_DEFAULT_API_BASE_URL,
    CONF_DEFAULT_API_USER,
    CONF_DEFAULT_API_PWD,
)


_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chuck Charger Control."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def _show_setup_form(
        self, errors: dict[str, str] | None = None
    ) -> FlowResult:
        """Show the setup form to the user."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("friendly_name", default="My Chargebox"): cv.string,
                    vol.Required(
                        "base_url", default=CONF_DEFAULT_API_BASE_URL
                    ): cv.string,
                    vol.Required("auth_user", default=CONF_DEFAULT_API_USER): cv.string,
                    vol.Required("auth_pass", default=CONF_DEFAULT_API_PWD): cv.string,
                    vol.Required(
                        "cfg_phase_order_conn1", default=PHASE_ORDER_DICT_DEFAULT_CFG
                    ): vol.In(PHASE_ORDER_DICT),
                    vol.Required(
                        "cfg_phase_order_conn2", default=PHASE_ORDER_DICT_DEFAULT_CFG
                    ): vol.In(PHASE_ORDER_DICT),
                    vol.Optional(
                        "have_net_current_sensor",
                        default=False,
                        description="have_net_current_sensor",
                    ): cv.boolean,
                    vol.Optional(
                        "is_connected_to_ocpp",
                        default=False,
                        description="is_connected_to_ocpp",
                    ): cv.boolean,
                }
            ),
            errors=errors or {},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        if user_input is None:
            return await self._show_setup_form(user_input)

        errors = {}

        url: str | None = user_input["base_url"]
        username: str | None = user_input["auth_user"]
        password: str | None = user_input["auth_pass"]

        chuckapi = ChuckChargeBox(self.hass, url, username, password)

        try:
            await self.hass.async_add_executor_job(chuckapi.update)
        except ChuckAuthError:
            errors["base"] = "invalid_auth"
            return await self._show_setup_form(errors)
        except ChuckRestTimeout:
            errors["base"] = "timeout"
            return await self._show_setup_form(errors)
        except ChuckRestError as err:
            errors["base"] = err.http_message
            return await self._show_setup_form(errors)

        return self.async_create_entry(
            title=user_input["friendly_name"],
            data=user_input,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.data = self.config_entry.data

    async def _show_config_form(
        self, errors: dict[str, str] | None = None
    ) -> FlowResult:
        cfg = self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "friendly_name", default=cfg.get("friendly_name")
                    ): cv.string,
                    vol.Required("base_url", default=cfg.get("base_url")): cv.string,
                    vol.Required("auth_user", default=cfg.get("auth_user")): cv.string,
                    vol.Required("auth_pass", default=cfg.get("auth_pass")): cv.string,
                    vol.Required(
                        "cfg_phase_order_conn1",
                        default=cfg.get("cfg_phase_order_conn1"),
                    ): vol.In(PHASE_ORDER_DICT),
                    vol.Required(
                        "cfg_phase_order_conn2",
                        default=cfg.get("cfg_phase_order_conn2"),
                    ): vol.In(PHASE_ORDER_DICT),
                    vol.Optional(
                        "have_net_current_sensor",
                        default=cfg.get("have_net_current_sensor"),
                    ): cv.boolean,
                    vol.Optional(
                        "is_connected_to_ocpp",
                        default=cfg.get("is_connected_to_ocpp"),
                    ): cv.boolean,
                }
            ),
            errors=errors,
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        if user_input is not None:
            self.config_entry.data = user_input
            url: str | None = user_input["base_url"]
            username: str | None = user_input["auth_user"]
            password: str | None = user_input["auth_pass"]

            chuckapi = ChuckChargeBox(self.hass, url, username, password)

            try:
                await self.hass.async_add_executor_job(chuckapi.update)
            except ChuckAuthError:
                errors["base"] = "invalid_auth"
                return await self._show_config_form(errors)
            except ChuckRestTimeout:
                errors["base"] = "timeout"
                return await self._show_config_form(errors)
            except ChuckRestError as err:
                errors["base"] = err.http_message
                return await self._show_config_form(errors)

            return self.async_create_entry(
                title=user_input["friendly_name"],
                data=user_input,
            )

        return await self._show_config_form(errors=errors)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
