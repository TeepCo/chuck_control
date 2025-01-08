"""Config flow for Chuck Charger Control integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .chuck_rest import ChuckAuthError, ChuckChargeBox, ChuckRestError, ChuckRestTimeout
from .const import (
    CONF_DEFAULT_API_BASE_URL,
    CONF_DEFAULT_API_PWD,
    CONF_DEFAULT_API_USER,
    DOMAIN,
    PHASE_ORDER_DICT,
    PHASE_ORDER_DICT_DEFAULT_CFG,
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
        return ChuckOptionsFlowHandler()

    async def _show_setup_form(
        self, errors: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
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
    ) -> config_entries.ConfigFlowResult:
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



class ChuckOptionsFlowHandler(config_entries.OptionsFlow):


    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors = {}
        data_schema = vol.Schema(
            {
                vol.Required(
                    "friendly_name", default=self.config_entry.data.get("friendly_name")
                ): cv.string,
                vol.Required("base_url", default=self.config_entry.data.get("base_url")): cv.string,
                vol.Required("auth_user", default=self.config_entry.data.get("auth_user")): cv.string,
                vol.Required("auth_pass", default=self.config_entry.data.get("auth_pass")): cv.string,
                vol.Required(
                    "cfg_phase_order_conn1",
                    default=self.config_entry.data.get("cfg_phase_order_conn1"),
                ): vol.In(PHASE_ORDER_DICT),
                vol.Required(
                    "cfg_phase_order_conn2",
                    default=self.config_entry.data.get("cfg_phase_order_conn2"),
                ): vol.In(PHASE_ORDER_DICT),
                vol.Optional(
                    "have_net_current_sensor",
                    default=self.config_entry.data.get("have_net_current_sensor"),
                ): cv.boolean,
                vol.Optional(
                    "is_connected_to_ocpp",
                    default=self.config_entry.data.get("is_connected_to_ocpp"),
                ): cv.boolean,
            }
        )
        if user_input is not None:
            url: str | None = user_input["base_url"]
            username: str | None = user_input["auth_user"]
            password: str | None = user_input["auth_pass"]

            chuckapi = ChuckChargeBox(self.hass, url, username, password)



            try:
                await self.hass.async_add_executor_job(chuckapi.update)
            except ChuckAuthError:
                errors["base"] = "invalid_auth"
                return  self.async_show_form(data_schema=self.add_suggested_values_to_schema(data_schema,self.config_entry.options), errors=errors)
            except ChuckRestTimeout:
                errors["base"] = "timeout"
                return  self.async_show_form(data_schema=self.add_suggested_values_to_schema(data_schema,self.config_entry.options), errors=errors)
            except ChuckRestError as err:
                errors["base"] = err.http_message
                return  self.async_show_form(data_schema=self.add_suggested_values_to_schema(data_schema,self.config_entry.options), errors=errors)

            return self.async_create_entry(
                data=user_input,
            )

        return self.async_show_form(data_schema=self.add_suggested_values_to_schema(data_schema,self.config_entry.options), errors=errors)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
