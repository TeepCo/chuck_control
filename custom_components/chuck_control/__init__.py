"""The Chuck Charger Control integration."""
from __future__ import annotations
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    PlatformNotReady,
)
from .const import DOMAIN, PHASE_ORDER_DICT, CONF_HAVE_NET_CURRENT_SENSOR
import logging
import asyncio
from . import chuck_rest


PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chuck Charger Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    chargebox_cfg = dict(entry.data)
    have_net_current_sensor = chargebox_cfg[CONF_HAVE_NET_CURRENT_SENSOR]

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

    try:
        await hass.async_add_executor_job(chargebox.update)
    except chuck_rest.ChuckRestTimeout:
        raise ConfigEntryNotReady(
            f"Could not connect to chargebox {chargebox_cfg['friendly_name']} at {chargebox_cfg['base_url']}"
        )
    except chuck_rest.ChuckAuthError:
        raise ConfigEntryAuthFailed(
            f"Wrong username or password supplied for chargebox {chargebox_cfg['friendly_name']} at {chargebox_cfg['base_url']}"
        )
    except:
        raise ConfigEntryNotReady(
            f"Unknown error connecting to chargebox {chargebox_cfg['friendly_name']} at {chargebox_cfg['base_url']}"
        )

    # Registers update listener to update config entry when options are updated.
    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    # Store a reference to the unsubscribe function to cleanup if an entry is unloaded.
    chargebox_cfg["unsub_options_update_listener"] = unsub_options_update_listener
    chargebox_cfg.update({"chargebox": chargebox})
    hass.data[DOMAIN][entry.entry_id] = chargebox_cfg

    # Forward the setup to the sensor platform.
    await asyncio.gather(
        *(
            hass.config_entries.async_forward_entry_setup(entry, platform)
            for platform in PLATFORMS
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
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
