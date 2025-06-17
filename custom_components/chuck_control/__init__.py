"""The Chuck Charger Control integration."""

from __future__ import annotations
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    PlatformNotReady,
)

from .const import DOMAIN, PHASE_ORDER_DICT, CONF_HAVE_NET_CURRENT_SENSOR
import logging
import asyncio
from . import chuck_rest
from .sensor import async_aiohttp_api_response

# Define platforms to set up
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)

# Define default update interval
UPDATE_INTERVAL = timedelta(seconds=2)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chuck Charger Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    chargebox_cfg = dict(entry.options)
    have_net_current_sensor = chargebox_cfg[CONF_HAVE_NET_CURRENT_SENSOR]

    # Create ChuckChargeBox instance
    chargebox = chuck_rest.ChuckChargeBox(
        hass=hass,
        base_url=chargebox_cfg["base_url"],
        auth_name=chargebox_cfg["auth_user"],
        auth_pass=chargebox_cfg["auth_pass"],
        friendly_name=chargebox_cfg["friendly_name"],
        have_net_current_sensor=have_net_current_sensor,
        phase_order=[
            chargebox_cfg["cfg_phase_order_conn1"],
            chargebox_cfg["cfg_phase_order_conn2"],
        ],
    )

    # Create the coordinator that will handle updating data from the API
    coordinator = chuck_rest.ChuckCoordinator(
        hass=hass,
        charge_box=chargebox,
        update_interval=UPDATE_INTERVAL,
    )

    try:
        # Fetch initial data
        await coordinator.async_config_entry_first_refresh()
    except chuck_rest.ChuckRestTimeout:
        raise ConfigEntryNotReady(
            f"Could not connect to chargebox {chargebox_cfg['friendly_name']} at {chargebox_cfg['base_url']}"
        )
    except chuck_rest.ChuckAuthError:
        raise ConfigEntryAuthFailed(
            f"Wrong username or password supplied for chargebox {chargebox_cfg['friendly_name']} at {chargebox_cfg['base_url']}"
        )
    except Exception as e:
        _LOGGER.exception(f"Error during setup: {e}")  # log the error
        raise ConfigEntryNotReady(
            f"Unknown error connecting to chargebox {chargebox_cfg['friendly_name']} at {chargebox_cfg['base_url']}"
        )

    if not await async_aiohttp_api_response(hass, f"{chargebox.base_url}/api/status"):
        raise ConfigEntryNotReady

    # Registers update listener to update config entry when options are updated.
    unsub_options_update_listener = entry.add_update_listener(options_update_listener)

    # Store a reference to the unsubscribe function to cleanup if an entry is unloaded.
    chargebox_cfg["unsub_options_update_listener"] = unsub_options_update_listener
    chargebox_cfg.update(
        {
            "chargebox": chargebox,
            "coordinator": coordinator,
        }
    )
    hass.data[DOMAIN][entry.entry_id] = chargebox_cfg

    # Register service
    hass.services.async_register(
        DOMAIN,
        "get_integration_config",
        lambda service_call: entry.as_dict(),
        supports_response=SupportsResponse.ONLY,
    )

    async def update_unitconfig_data(service):
        if "values" not in service.data:
            _LOGGER.error(
                "Service call 'update_unitconfig_data' requires 'values' parameter"
            )
            return
        if "persist" not in service.data:
            _LOGGER.error(
                "Service call 'update_unitconfig_data' requires 'persist' parameter"
            )
            return
        values = service.data["values"]
        persist = service.data["persist"]
        if not isinstance(values, dict):
            _LOGGER.error(
                "Service call 'update_unitconfig_data' requires 'values' to be a dictionary"
            )
            return
        if not isinstance(persist, bool):
            _LOGGER.error(
                "Service call 'update_unitconfig_data' requires 'persist' to be a boolean"
            )
            return
        await chargebox.set_unitconfig_values(values, persist=persist)

    hass.services.async_register(
        DOMAIN,
        "update_unitconfig_data",
        update_unitconfig_data,
    )

    # Set up all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Cancel all listen callbacks and clean up references
        hass.data[DOMAIN][entry.entry_id]["unsub_options_update_listener"]()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        new = {**config_entry.data}
        new["cfg_phase_order_conn1"] = config_entry.data["cfg_phase_order"]
        new["cfg_phase_order_conn2"] = config_entry.data["cfg_phase_order"]
        del new["cfg_phase_order"]

        config_entry.version = 2
        hass.config_entries.async_update_entry(config_entry, data=new)

        _LOGGER.info("Migration to version %s successful", config_entry.version)

    return True
