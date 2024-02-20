import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
)
from homeassistant.const import (
    CONF_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    UnitOfElectricCurrent,
    UnitOfPower,
    UnitOfEnergy,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import Any
from datetime import timedelta
from .const import DOMAIN, CONF_HAVE_NET_CURRENT_SENSOR


_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=2)
DEFAULT_BASE_URL = "https://demo.evexpert.eu/demo/"
DEFAULT_AUTH_NAME = "admin"
DEFAULT_AUTH_PASS = "admin"
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_URL): cv.string,
        vol.Optional(CONF_USERNAME, default=DEFAULT_AUTH_NAME): cv.string,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_AUTH_PASS): cv.string,
        vol.Optional(CONF_HAVE_NET_CURRENT_SENSOR, default=False): cv.boolean,
    }
)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup sensors from a config entry created in the integrations UI."""
    _LOGGER.debug("ASYNC SETUP ENTRY")
    chargebox_cfg = config_entry.data
    have_net_current_sensor = chargebox_cfg[CONF_HAVE_NET_CURRENT_SENSOR]
    chargebox = hass.data[DOMAIN][config_entry.entry_id]["chargebox"]

    if chargebox.info:
        async_add_entities([ChargeBoxTotal(chargebox)])
        async_add_entities([ChargeBoxSessionEnergy(chargebox)])

        to_add = []
        for connector in range(chargebox.get_connectors_count()):
            to_add.append(ConnectorCurrent(chargebox, connector + 1))
            to_add.append(ConnectorStatus(chargebox, connector + 1))
            to_add.append(ConnectorVoltage(chargebox, connector + 1))
            to_add.append(ConnectorPower(chargebox, connector + 1))

            to_add.append(ConnectorActual(chargebox, connector + 1))
            to_add.append(ConnectorTotal(chargebox, connector + 1))
            to_add.append(ConnectorInternalTemp(chargebox, connector + 1))

            to_add.append(ConnectorCurrentPhase(chargebox, connector + 1, 1))
            to_add.append(ConnectorCurrentPhase(chargebox, connector + 1, 2))
            to_add.append(ConnectorCurrentPhase(chargebox, connector + 1, 3))
            if have_net_current_sensor and connector + 1 == 1:
                to_add.append(NetCurrentSensor(chargebox, connector + 1))
                to_add.append(NetCurrentPhaseSensor(chargebox, 1))
                to_add.append(NetCurrentPhaseSensor(chargebox, 2))
                to_add.append(NetCurrentPhaseSensor(chargebox, 3))
        async_add_entities(to_add)
    else:
        _LOGGER.error(f"Cannot add {chargebox}")

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_max_charging_current",
        {
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("max_charging_current"): cv.positive_int,
        },
        "set_max_charging_current",
    )


def get_friendly_name(
    cls,
    charger_name: bool = True,
    charger_serial: bool = False,
    connector: bool = True,
    phase: bool = True,
):
    name = ""
    if charger_name and hasattr(cls, "chargebox"):
        name += cls.chargebox.get_friendly_name()
    if charger_serial and hasattr(cls, "chargebox"):
        name += f"/{cls.chargebox.info['serialNumber']}"
    if connector and hasattr(cls, "connector_id"):
        name += f"/Connector #{cls.connector_id}"
    if phase and hasattr(cls, "phase_number"):
        name += f"/L{cls.phase_number}"
    if hasattr(cls, "friendly_name_appendix"):
        name += f"/{cls.friendly_name_appendix}"
    return name


class NetCurrentSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.CURRENT

    def __init__(self, chargebox, connector_id) -> None:
        self.chargebox = chargebox
        self.connector_id = str(connector_id)
        self._attr_name = f"NtCurentSenzor Connector {connector_id} status"
        self.friendly_name_appendix = "External EVSE net sensor"
        self.friendly_name = get_friendly_name(self, connector=False)

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_net_current_sensor"

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.CURRENT

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfElectricCurrent.AMPERE

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def state(self) -> Any:
        ext = self.chargebox.status["connectors"][self.connector_id]["packet"]["ext"]
        total_current = (
            ext.get("exmcl1", 0) + ext.get("exmcl2", 0) + ext.get("exmcl3", 0)
        )
        return float(total_current)

    @property
    def state_attributes(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "ext": self.chargebox.status["connectors"][self.connector_id]["packet"][
                "ext"
            ],
        }

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()


class NetCurrentPhaseSensor(SensorEntity):
    def __init__(self, chargebox, phase_number) -> None:
        self.chargebox = chargebox
        self.phase_number = phase_number
        self.friendly_name_appendix = "Net current"
        self.friendly_name = get_friendly_name(self)

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_L{self.phase_number}_net_current"

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.CURRENT

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfElectricCurrent.AMPERE

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def state(self) -> Any:
        return round(self.chargebox.get_net_current_for_L(self.phase_number), 2)

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def icon(self) -> str:
        if self.state > 0:
            return f"mdi:numeric-{self.phase_number}-box-outline"
        return f"mdi:numeric-{self.phase_number}"


class ConnectorStatus(SensorEntity):
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, chargebox, connector_id) -> None:
        self.chargebox = chargebox
        self.connector_id = str(connector_id)
        self._attr_name = f"Connector {connector_id} status"
        self.friendly_name_appendix = "Status"
        self.friendly_name = get_friendly_name(self)

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_status"

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def state(self) -> Any:
        return self.chargebox.get_connector_status(self.connector_id)

    @property
    def state_attributes(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "session_energy": self.chargebox.get_connector_session_energy(
                self.connector_id
            ),
            "total_energy": self.chargebox.get_connector_total_energy(
                self.connector_id
            ),
            "charging_current": self.chargebox.get_connector_current(self.connector_id),
            "max_enabled_current": self.chargebox.get_connector_max_charging_current(
                self.connector_id
            ),
            "charging_status": self.chargebox.status["connectors"][self.connector_id][
                "packet"
            ]["chargingStatus"],
            "lock_status": self.chargebox.status["connectors"][self.connector_id][
                "packet"
            ]["lockStatus"],
            "car_connected": self.chargebox.status["connectors"][self.connector_id][
                "carConnected"
            ],
            "internal_temp": self.chargebox.status["connectors"][self.connector_id][
                "packet"
            ]["internalTemperature"],
            "warnings": self.chargebox.status["connectors"][self.connector_id][
                "packet"
            ]["warnings"],
            "errors": self.chargebox.status["connectors"][self.connector_id]["packet"][
                "errors"
            ],
            "phase_order": self.chargebox.get_phase_order_cfg(),
            "auth": self.chargebox.get_auth_status(),
        }

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    async def set_max_charging_current(entity, max_charging_current=0):
        await entity.chargebox.set_connector_max_charging_current(
            entity.connector_id, max_charging_current
        )


class ConnectorCurrent(SensorEntity):
    def __init__(self, chargebox, connector_id) -> None:
        self.chargebox = chargebox
        self.connector_id = connector_id
        self._attr_name = f"Connector {connector_id} Current"
        self.friendly_name_appendix = "Total current"
        self.friendly_name = get_friendly_name(self)

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_total_current"

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.CURRENT

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfElectricCurrent.AMPERE

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def state(self) -> Any:
        return round(self.chargebox.get_connector_current(self.connector_id))

    @property
    def state_attributes(self) -> dict[str, Any]:
        cid = str(self.connector_id)
        return {
            "connector_id ": self.connector_id,
            "current_L1": self.chargebox.get_current_for_connector_L(cid, 1),
            "current_L2": self.chargebox.get_current_for_connector_L(cid, 2),
            "current_L3": self.chargebox.get_current_for_connector_L(cid, 3),
            "max_charging_current": self.chargebox.info["config"][f"MaxCurrent_{cid}"],
            "temp_charging_current": self.chargebox.get_connector_tmp_charging_limit(
                self.connector_id
            ),
            "default_max_charging_current": self.chargebox.info.get("config").get(
                "MaxDefaultCurrent"
            ),
            "max_current_net_override": self.chargebox.info.get("config").get(
                "MaxCurrentNet"
            ),
            "wanted_state": self.chargebox.status["connectors"][cid]["status"],
            "charging_state": self.chargebox.status["connectors"][
                str(self.connector_id)
            ]["packet"]["chargingStatus"],
            "lock_state": self.chargebox.status["connectors"][str(self.connector_id)][
                "packet"
            ]["lockStatus"],
            "car_connected": self.chargebox.status["connectors"][
                str(self.connector_id)
            ]["carConnected"],
            "actual_wh": self.chargebox.status["connectors"][str(self.connector_id)][
                "packet"
            ]["actualWh"],
            "total_wh": self.chargebox.status["connectors"][str(self.connector_id)][
                "packet"
            ]["totalWh"],
        }

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def icon(self) -> str:
        if self.chargebox.is_connector_charging(self.connector_id):
            return "mdi:flash"
        return "mdi:flash-outline"

    async def set_max_charging_current(entity, max_charging_current=0):
        await entity.chargebox.set_connector_max_charging_current(
            entity.connector_id, max_charging_current
        )


class ConnectorCurrentPhase(SensorEntity):
    def __init__(self, chargebox, connector_id, phase_number) -> None:
        self.chargebox = chargebox
        self.connector_id = connector_id
        self.phase_number = phase_number
        self.friendly_name_appendix = "Current"
        self.friendly_name = get_friendly_name(self)

    @property
    def entity_registry_enabled_default(self) -> bool:
        return False

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_phase_{self.phase_number}_current_"

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.CURRENT

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfElectricCurrent.AMPERE

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def state(self) -> Any:
        return round(
            self.chargebox.get_current_for_connector_L(
                self.connector_id, self.phase_number
            ),
            2,
        )

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def icon(self) -> str:
        if self.state > 0:
            return f"mdi:numeric-{self.phase_number}-box-outline"
        return f"mdi:numeric-{self.phase_number}"


class ConnectorVoltage(SensorEntity):
    def __init__(self, chargebox, connector_id) -> None:
        self.chargebox = chargebox
        self.connector_id = connector_id
        self.friendly_name_appendix = "Voltage"
        self.friendly_name = get_friendly_name(self)

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.VOLTAGE

    @property
    def device_info(self) -> DeviceInfo | None:
        return self.chargebox.get_device_info()

    @property
    def state_class(self) -> SensorStateClass | str | None:
        return SensorStateClass.MEASUREMENT

    @property
    def state(self) -> Any:
        return round(self.chargebox.get_connector_voltage(self.connector_id), 2)

    @property
    def unique_id(self) -> str | None:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_voltage"

    @property
    def entity_registry_enabled_default(self) -> bool:
        return False


class ConnectorPower(SensorEntity):
    def __init__(self, chargebox, connector_id) -> None:
        self.chargebox = chargebox
        self.connector_id = connector_id
        self.friendly_name_appendix = "Actual power"
        self.friendly_name = get_friendly_name(self)

    @property
    def entity_registry_enabled_default(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return SensorDeviceClass.POWER

    @property
    def device_info(self) -> DeviceInfo | None:
        return self.chargebox.get_device_info()

    @property
    def state_class(self) -> SensorStateClass | str | None:
        return SensorStateClass.MEASUREMENT

    @property
    def state(self) -> Any:
        return self.chargebox.get_connector_power_kw(self.connector_id)

    @property
    def unit_of_measurement(self) -> str | None:
        return UnitOfPower.KILO_WATT

    @property
    def unique_id(self) -> str | None:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_actual_power"


class ConnectorTotal(SensorEntity):
    def __init__(self, chargebox, connector_id) -> None:
        self.chargebox = chargebox
        self.connector_id = connector_id
        self.friendly_name_appendix = "Total energy"
        self.friendly_name = get_friendly_name(self)

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.ENERGY

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.TOTAL

    @property
    def state(self) -> Any:
        return round(
            self.chargebox.get_connector_total_energy(self.connector_id) / 1000, 2
        )

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_energy_total"


class ConnectorActual(SensorEntity):
    def __init__(self, chargebox, connecotr_id) -> None:
        self.chargebox = chargebox
        self.connector_id = connecotr_id
        self.friendly_name_appendix = "Actual energy"
        self.friendly_name = get_friendly_name(self)

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.ENERGY

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def state(self) -> Any:
        return round(
            self.chargebox.get_connector_session_energy(self.connector_id) / 1000, 2
        )

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_energy_actual"


class ChargeBoxTotal(SensorEntity):
    def __init__(self, chargebox) -> None:
        self.chargebox = chargebox
        self.friendly_name_appendix = "Total energy"
        self.friendly_name = get_friendly_name(self)

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.ENERGY

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.TOTAL

    @property
    def state(self) -> Any:
        return round(self.chargebox.get_energy_total() / 1000, 2)

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_energy_total"

    @property
    def state_attributes(self) -> dict[str, Any]:
        return {"connector_count ": self.chargebox.get_connectors_count()}


class ChargeBoxSessionEnergy(SensorEntity):
    def __init__(self, chargebox) -> None:
        self.chargebox = chargebox
        self.friendly_name_appendix = "Actual energy"
        self.friendly_name = get_friendly_name(self)

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()

    @property
    def state(self) -> Any:
        return round(self.chargebox.get_energy_session() / 1000, 2)

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_energy_actual"

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.ENERGY

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfEnergy.KILO_WATT_HOUR

    def update(self) -> None:
        self.chargebox.update()

    @property
    def state_attributes(self) -> dict[str, Any]:
        return {"connector_count ": self.chargebox.get_connectors_count()}


class ConnectorInternalTemp(SensorEntity):
    def __init__(self, chargebox, connector_id) -> None:
        self.chargebox = chargebox
        self.connector_id = str(connector_id)
        self._attr_name = f"NtCurentSenzor Connector {connector_id} status"
        self.friendly_name_appendix = "Internal temp"
        self.friendly_name = get_friendly_name(self)

    @property
    def unique_id(self) -> str:
        return f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_internal_temp"

    @property
    def name(self) -> str:
        return self.friendly_name

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def unit_of_measurement(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def state(self) -> Any:
        return float(
            self.chargebox.status["connectors"][self.connector_id]["packet"].get(
                "internalTemperature", 0
            )
        )

    @property
    def device_info(self) -> DeviceInfo:
        return self.chargebox.get_device_info()
