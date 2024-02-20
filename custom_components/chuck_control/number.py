import logging
from homeassistant import config_entries, core
from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    _LOGGER.debug("ASYNC SETUP ENTRY")
    chargebox = hass.data[DOMAIN][config_entry.entry_id]["chargebox"]
    to_add = []
    for connector in range(chargebox.get_connectors_count()):
        to_add.append(MaxChargingLimitConnector(chargebox, connector + 1))

    async_add_entities(to_add)


class MaxChargingLimitConnector(NumberEntity):
    def __init__(self, chargebox, connectorId) -> None:
        super().__init__()
        self.chargebox = chargebox
        self.cid = str(connectorId)
        self.test_value = 1.0

    @property
    def name(self) -> str:
        # return f"C{self.cid} Charging limit"
        return f"Connector {self.cid} max/{self.chargebox.get_friendly_name()}/{self.chargebox.info['serialNumber']}"

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfElectricCurrent.AMPERE

    @property
    def icon(self) -> str:
        return "mdi:hammer-screwdriver"

    @property
    def unique_id(self) -> str:
        return f"tmp_max_current_connector_{self.cid}_{self.chargebox.info['serialNumber']}"

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def value(self) -> float:
        return self.chargebox.get_connector_tmp_charging_limit(self.cid)

    @property
    def min_value(self) -> float:
        return 0.0

    @property
    def max_value(self) -> float:
        return float(self.chargebox.info.get("config").get(f"MaxDefaultCurrent"))

    @property
    def step(self) -> float:
        return 1.0

    def set_value(self, value: float) -> None:
        return self.chargebox.set_connector_tmp_charging_limit(self.cid, value)
