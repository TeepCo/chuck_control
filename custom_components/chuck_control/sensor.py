import logging
from datetime import timedelta
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries, core
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_platform import async_get_current_platform

from .const import CONF_HAVE_NET_CURRENT_SENSOR, DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://demo.evexpert.eu/demo/"
DEFAULT_AUTH_NAME = "admin"
DEFAULT_AUTH_PASS = "admin"

SENSOR_PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_URL): cv.string,
        vol.Optional(CONF_USERNAME, default=DEFAULT_AUTH_NAME): cv.string,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_AUTH_PASS): cv.string,
        vol.Optional(CONF_HAVE_NET_CURRENT_SENSOR, default=False): cv.boolean,
    }
)


# Utility function to safely extract data with defaults
def get_data(data: dict, keys: list[str], default: Any = None) -> Any:
    """Safely extracts nested data from a dictionary."""
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


async def async_aiohttp_api_response(hass: core.HomeAssistant, url: str) -> bool:
    """Detect if the charging options API is available using aiohttp."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(url) as response:
            if response.status == 200:
                _LOGGER.info("Charging options API detected successfully at %s", url)
                return True
            _LOGGER.warning(
                "Charging options API at %s returned status code: %s",
                url,
                response.status,
            )
            return False
    except aiohttp.ClientError as err:
        _LOGGER.warning("Error connecting to charging options API at %s: %s", url, err)
        return False
    except Exception as excep:
        _LOGGER.exception(
            "Unexpected exception checking charging options API: %s", excep
        )
        return False


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up sensors from a config entry created in the integrations UI."""
    _LOGGER.debug("ASYNC SETUP ENTRY")

    chargebox_cfg = config_entry.options
    have_net_current_sensor = chargebox_cfg[CONF_HAVE_NET_CURRENT_SENSOR]
    chargebox = hass.data[DOMAIN][config_entry.entry_id]["chargebox"]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]  # Get coordinator

    entities = []

    # Add chargebox level sensors
    entities.append(ChargeBoxTotal(chargebox, coordinator))
    entities.append(ChargeBoxSessionEnergy(chargebox, coordinator))

    # Conditionally add charging options sensor
    if await async_aiohttp_api_response(
        hass, f"{chargebox.base_url}/api/chargingOptions"
    ):
        entities.append(ChargingOptions(chargebox, coordinator))

    # Add connector level sensors
    for connector in range(1, chargebox.get_connectors_count() + 1):
        entities.append(ConnectorCurrent(chargebox, coordinator, connector))
        entities.append(ConnectorStatus(chargebox, coordinator, connector))
        entities.append(ConnectorVoltage(chargebox, coordinator, connector))
        entities.append(ConnectorPower(chargebox, coordinator, connector))
        entities.append(ConnectorActual(chargebox, coordinator, connector))
        entities.append(ConnectorTotal(chargebox, coordinator, connector))
        entities.append(ConnectorInternalTemp(chargebox, coordinator, connector))

        # Add connector phase level sensors
        for phase in range(1, 4):
            entities.append(
                ConnectorCurrentPhase(chargebox, coordinator, connector, phase)
            )

        # Conditionally add net current sensors
        if have_net_current_sensor and connector == 1:
            entities.append(NetCurrentSensor(chargebox, coordinator, connector))
            for phase in range(1, 4):
                entities.append(NetCurrentPhaseSensor(chargebox, coordinator, phase))

    async_add_entities(entities, True)

    platform = async_get_current_platform()
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


class BaseChuckEntity(SensorEntity):
    """Base class for Chuck entities."""

    _attr_has_entity_name = True

    def __init__(self, chargebox, coordinator, connector_id=None, phase_number=None):
        """Initialize the sensor."""
        self.chargebox = chargebox
        self.coordinator = coordinator
        self.connector_id = connector_id
        self.phase_number = phase_number
        self._attr_device_info = chargebox.get_device_info()

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class NetCurrentSensor(BaseChuckEntity):
    """External EVSE net sensor."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "External EVSE net sensor"
        self._attr_name = get_friendly_name(self, connector=False)
        self._attr_unique_id = (
            f"{self.chargebox.info['serialNumber']}_net_current_sensor"
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        ext = get_data(
            self.coordinator.data,
            ["status", "connectors", str(self.connector_id), "packet", "ext"],
            {},
        )
        total_current = sum(ext.get(f"exmcl{i}", 0) for i in range(1, 4))
        return float(total_current)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            "connector_id": self.connector_id,
            "ext": get_data(
                self.coordinator.data,
                ["status", "connectors", str(self.connector_id), "packet", "ext"],
                {},
            ),
        }


class NetCurrentPhaseSensor(BaseChuckEntity):
    """Net current phase sensor."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_entity_registry_enabled_default = False

    def __init__(self, chargebox, coordinator, phase_number) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, phase_number=phase_number)
        self.friendly_name_appendix = "Net current"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = (
            f"{self.chargebox.info['serialNumber']}_L{self.phase_number}_net_current"
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        # We now read directly from coordinator data
        return round(self.get_net_current_for_L(self.phase_number), 2)

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        return (
            f"mdi:numeric-{self.phase_number}-box-outline"
            if self.native_value > 0
            else f"mdi:numeric-{self.phase_number}"
        )

    def get_net_current_for_L(self, L):
        try:
            physical_L = str(L)
            return get_data(
                self.coordinator.data,
                ["status", "connectors", "1", "packet", "ext", f"exmcl{physical_L}"],
                0,
            )
        except Exception as e:
            _LOGGER.warning(f"Error getting net current for L{L}: {e}")
            return 0


class ConnectorStatus(BaseChuckEntity):
    """Connector status sensor."""

    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "Status"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_status"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        status = get_data(
            self.coordinator.data,
            ["status", "connectors", str(self.connector_id), "status"],
            "unknown",
        )
        return status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        connector_data = get_data(
            self.coordinator.data,
            ["status", "connectors", str(self.connector_id), "packet"],
            {},
        )
        car_connected = get_data(
            self.coordinator.data,
            ["status", "connectors", str(self.connector_id), "carConnected"],
            False,
        )

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
            "charging_status": connector_data.get("chargingStatus"),
            "lock_status": connector_data.get("lockStatus"),
            "car_connected": car_connected,
            "internal_temp": connector_data.get("internalTemperature"),
            "warnings": connector_data.get("warnings"),
            "errors": connector_data.get("errors"),
            "phase_order": self.chargebox.get_phase_order_cfg(),
            "auth": get_data(self.coordinator.data, ["status", "authTag"], "unknown"),
        }

    async def set_max_charging_current(self, max_charging_current=0):
        """Service to set max charging current."""
        await self.chargebox.set_connector_max_charging_current(
            self.connector_id, max_charging_current
        )


class ConnectorCurrent(BaseChuckEntity):
    """Connector current sensor."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "Total current"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_total_current"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return round(self.get_connector_current(), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        cid = str(self.connector_id)
        status = get_data(self.coordinator.data, ["status", "connectors", cid], {})
        packet = get_data(
            self.coordinator.data, ["status", "connectors", cid, "packet"], {}
        )

        return {
            "connector_id ": self.connector_id,
            "charger_id": self.chargebox.info["serialNumber"],
            "current_L1": self.get_current_for_connector_L(cid, 1),
            "current_L2": self.get_current_for_connector_L(cid, 2),
            "current_L3": self.get_current_for_connector_L(cid, 3),
            "max_charging_current": self.chargebox.info["config"].get(
                f"MaxCurrent_{cid}", 0
            ),
            "temp_charging_current": self.chargebox.get_connector_tmp_charging_limit(
                self.connector_id
            ),
            "default_max_charging_current": self.chargebox.info.get("config", {}).get(
                "MaxDefaultCurrent"
            ),
            "max_current_net_override": self.chargebox.info.get("config", {}).get(
                "MaxCurrentNet"
            ),
            "wanted_state": status.get("status"),
            "charging_state": packet.get("chargingStatus"),
            "lock_state": packet.get("lockStatus"),
            "car_connected": status.get("carConnected"),
            "actual_wh": packet.get("actualWh"),
            "total_wh": packet.get("totalWh"),
        }

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        return "mdi:flash" if self.is_connector_charging() else "mdi:flash-outline"

    async def set_max_charging_current(self, max_charging_current=0):
        """Service to set max charging current."""
        await self.chargebox.set_connector_max_charging_current(
            self.connector_id, max_charging_current
        )

    def get_connector_current(self):
        try:
            return self.coordinator.data["status"]["connectors"][
                str(self.connector_id)
            ]["current"]
        except (KeyError, TypeError):
            return 0

    def get_current_for_connector_L(self, connector, L):
        try:
            if (
                not self.coordinator.data.get("status")
                or not self.chargebox.phase_order
            ):
                return 0.0

            # Safe access to indices
            if int(connector) <= 0 or int(connector) > len(self.chargebox.phase_order):
                return 0.0

            physical_L = self.chargebox.phase_order[int(connector) - 1][L - 1]
            return get_data(
                self.coordinator.data,
                [
                    "status",
                    "connectors",
                    str(connector),
                    "packet",
                    "ext",
                    f"crrntl{str(physical_L)}",
                ],
                0,
            )
        except Exception as e:
            _LOGGER.warning(
                f"Error getting current for connector {connector}, L{L}: {e}"
            )
            return 0.0

    def is_connector_charging(self) -> bool:
        try:
            charging_state = self.get_connector_charging_state()
            return charging_state.startswith("CHARGING") if charging_state else False
        except Exception as e:
            _LOGGER.warning(
                f"Error checking if connector {self.connector_id} is charging: {e}"
            )
            return False

    def get_connector_charging_state(self) -> str:
        try:
            return self.coordinator.data["status"]["connectors"][
                str(self.connector_id)
            ]["packet"]["chargingStatus"]
        except (KeyError, TypeError):
            return "UNKNOWN"


class ConnectorCurrentPhase(BaseChuckEntity):
    """Connector current phase sensor."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_entity_registry_enabled_default = False

    def __init__(self, chargebox, coordinator, connector_id, phase_number) -> None:
        """Initialize the sensor."""
        super().__init__(
            chargebox, coordinator, connector_id=connector_id, phase_number=phase_number
        )
        self.friendly_name_appendix = "Current"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_phase_{self.phase_number}_current_"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return round(
            self.get_current_for_connector_L(self.connector_id, self.phase_number), 2
        )

    @property
    def icon(self) -> str:
        """Return the icon of the sensor."""
        return (
            f"mdi:numeric-{self.phase_number}-box-outline"
            if self.native_value > 0
            else f"mdi:numeric-{self.phase_number}"
        )

    def get_current_for_connector_L(self, connector, L):
        try:
            if (
                not self.coordinator.data.get("status")
                or not self.chargebox.phase_order
            ):
                return 0.0

            # Safe access to indices
            if int(connector) <= 0 or int(connector) > len(self.chargebox.phase_order):
                return 0.0

            physical_L = self.chargebox.phase_order[int(connector) - 1][L - 1]
            return float(
                get_data(
                    self.coordinator.data,
                    [
                        "status",
                        "connectors",
                        str(connector),
                        "packet",
                        "ext",
                        f"crrntl{str(physical_L)}",
                    ],
                    0,
                )
            )
        except Exception as e:
            _LOGGER.warning(
                f"Error getting current for connector {connector}, L{L}: {e}"
            )
            return 0.0


class ConnectorVoltage(BaseChuckEntity):
    """Connector voltage sensor."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_entity_registry_enabled_default = True

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "Voltage"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_voltage"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return round(self.get_connector_voltage(), 2)

    def get_connector_voltage(self):
        try:
            return self.coordinator.data["status"]["connectors"][
                str(self.connector_id)
            ]["voltage"]
        except (KeyError, TypeError):
            return 0


class ConnectorPower(BaseChuckEntity):
    """Connector power sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_entity_registry_enabled_default = False

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "Actual power"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_actual_power"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self.get_connector_power_kw()

    def get_connector_power_kw(self):
        try:
            current = self.coordinator.data["status"]["connectors"][
                str(self.connector_id)
            ]["current"]
            voltage = self.coordinator.data["status"]["connectors"][
                str(self.connector_id)
            ]["voltage"]
            return round(current * voltage / 1000, 2)
        except (KeyError, TypeError):
            return 0


class ConnectorTotal(BaseChuckEntity):
    """Connector total energy sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "Total energy"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_energy_total"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return round(self.get_connector_total_energy() / 1000, 2)

    def get_connector_total_energy(self):
        try:
            return self.coordinator.data["status"]["connectors"][
                str(self.connector_id)
            ]["packet"]["totalWh"]
        except (KeyError, TypeError):
            return 0


class ConnectorActual(BaseChuckEntity):
    """Connector actual energy sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "Actual energy"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_energy_actual"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return round(self.get_connector_session_energy() / 1000, 2)

    def get_connector_session_energy(self):
        try:
            return self.coordinator.data["status"]["connectors"][
                str(self.connector_id)
            ]["packet"]["actualWh"]
        except (KeyError, TypeError):
            return 0


class ChargeBoxTotal(BaseChuckEntity):
    """Chargebox total energy sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, chargebox, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator)
        self.friendly_name_appendix = "Total energy"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_energy_total"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return round(self.chargebox.get_energy_total() / 1000, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {"connector_count ": self.chargebox.get_connectors_count()}


class ChargeBoxSessionEnergy(BaseChuckEntity):
    """Chargebox session energy sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, chargebox, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator)
        self.friendly_name_appendix = "Actual energy"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_energy_actual"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return round(self.chargebox.get_energy_session() / 1000, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {"connector_count ": self.chargebox.get_connectors_count()}


class ConnectorInternalTemp(BaseChuckEntity):
    """Connector internal temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator, connector_id=connector_id)
        self.friendly_name_appendix = "Internal temp"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_internal_temp"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        # Read directly from coordinator data
        return float(
            get_data(
                self.coordinator.data,
                [
                    "status",
                    "connectors",
                    str(self.connector_id),
                    "packet",
                    "internalTemperature",
                ],
                0,
            )
        )


class ChargingOptions(BaseChuckEntity):
    """Charging options sensor."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["SOLAR_ONLY", "BATTERY_RESERVE", "INSTANT_CHARGE", "UNSUPPORTED"]

    def __init__(self, chargebox, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(chargebox, coordinator)
        self.friendly_name_appendix = "Charging options"
        self._attr_name = get_friendly_name(self)
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_charging_options"
        self._attr_native_value = "UNSUPPORTED"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        charging_option = get_data(
            self.coordinator.data, ["basic_status", "chargingOption"], "UNSUPPORTED"
        )
        return (
            charging_option if charging_option in self._attr_options else "UNSUPPORTED"
        )
