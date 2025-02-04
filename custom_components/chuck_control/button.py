from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant import config_entries, core
from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.const import *
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from datetime import timedelta
import logging
from .const import DOMAIN, PHASE_ORDER_DICT
from .sensor import get_friendly_name

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=2)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    _LOGGER.debug("ASYNC SETUP ENTRY")
    chargebox = hass.data[DOMAIN][config_entry.entry_id]["chargebox"]
    charger_connected_to_ocpp = config_entry.data.get("is_connected_to_ocpp")
    to_add = get_buttons_to_add(chargebox, charger_connected_to_ocpp)
    async_add_entities(to_add)


def get_buttons_to_add(chargebox, charger_connected_to_ocpp) -> list[ButtonEntity]:
    """Return HA button entities used to control the charger based on its configuration.

    Args:
        chargebox (ChuckChargeBox): Charger that is currently being added
        charger_connected_to_ocpp (bool): True if charger is configured to communicate with a OCPP server (more on that below)

    Returns:
        buttons_to_add (list[ButtonEntity]): List of button entites to add to HA

    For each connector two buttons are added - one is to start the charging, the other one will stop it.
    If the charger is not connected to ocpp gateway (chuck is configured to use LOCAL or LOCAL_WITH_AUTH profile)
    the start button will simply enable charging which will start immediately if a car is connected and wants to charge.
    If the charger is connected to ocpp gateway (and chuck is using the OCPP profile) the start button will enable
    the charger and sends a start transaction request to the ocpp server, which will result in charging if allowed
    by the server.
    """
    buttons_to_add = []
    for connector in range(chargebox.get_connectors_count()):
        if charger_connected_to_ocpp:
            buttons_to_add.append(
                StartTransactionButton(chargebox=chargebox, connector_id=connector + 1)
            )

        buttons_to_add.extend(
            [
                EnableChargingButton(chargebox=chargebox, connector_id=connector + 1),
                DisableChargingButton(chargebox=chargebox, connector_id=connector + 1),
            ]
        )
    return buttons_to_add


class DisableChargingButton(ButtonEntity):
    def __init__(self, chargebox, connector_id) -> None:
        super().__init__()
        self.chargebox = chargebox
        self.connector_id = connector_id
        self.friendly_name_appendix = "Disable charging"
        self.friendly_name = get_friendly_name(self)

    async def async_press(self):
        await self.chargebox.set_connector_enable_charging(
            connectorId=self.connector_id, state=False
        )

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_disable_charging"

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()


class EnableChargingButton(ButtonEntity):
    def __init__(self, chargebox, connector_id) -> None:
        super().__init__()
        self.chargebox = chargebox
        self.connector_id = connector_id
        self.friendly_name_appendix = "Enable charging"
        self.friendly_name = get_friendly_name(self)

    async def async_press(self):
        await self.chargebox.set_connector_enable_charging(
            connectorId=self.connector_id, state=True
        )

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_enable_charging"

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()


class StartTransactionButton(ButtonEntity):
    def __init__(self, chargebox, connector_id) -> None:
        super().__init__()
        self.chargebox = chargebox
        self.connector_id = connector_id
        self.friendly_name_appendix = "Start transcation"
        self.friendly_name = get_friendly_name(self)

    async def async_press(self):
        await self.chargebox.set_connector_charging_start(
            action="Start", connector=self.connector_id
        )

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_transcation_start"

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()


