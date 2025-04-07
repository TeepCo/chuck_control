import json
import logging
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DOMAIN
from .const import PHASE_ORDER, PHASE_ORDER_DICT_DEFAULT_CFG

_LOGGER = logging.getLogger(__name__)

# Default update interval in seconds
UPDATE_INTERVAL = timedelta(seconds=1)


class ChuckCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Chuck Charger data."""

    def __init__(
        self,
        hass: HomeAssistant,
        charge_box: "ChuckChargeBox",
        update_interval: timedelta = UPDATE_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Chuck Charger",
            update_interval=update_interval,
        )
        self.charge_box = charge_box

    async def _async_update_data(self):
        """Fetch data from the Chuck Charger API."""
        try:
            await self.charge_box.update()
            # Return the current state to be stored in the coordinator
            return {
                "status": self.charge_box.status,
                "basic_status": self.charge_box.basic_status,
                "info": self.charge_box.info,
            }
        except ChuckRestTimeout as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except ChuckAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error updating Chuck Charger")
            raise UpdateFailed(f"Error updating Chuck Charger: {err}") from err


async def test_connection(
    hass: HomeAssistant, baseurl: str, username: str, password: str
):
    """Detect if the charging options API is available using aiohttp."""

    session = hass.helpers.aiohttp_client.async_get_clientsession()

    url = baseurl + "/api/admin/automation/status"

    _LOGGER.debug(f"request to {url}")
    timeout = 10
    auth = aiohttp.BasicAuth(username, password) if username and password else None

    try:
        async with session.get(url, auth=auth, timeout=timeout) as response:
            if response.status == 200:
                _LOGGER.info("API detected successfully at %s", url)
                return True
            if response.status == 401:
                raise ChuckAuthError("Wrong username or password supplied for Chuck API")
            _LOGGER.warning(
                "Charging options API at %s returned status code: %s",
                url,
                response.status,
            )
            return False  # API returned a non-200 status
    except aiohttp.ClientError as err:
        _LOGGER.warning(
            "Error connecting to charging options API at %s: %s", url, err
        )
        return False  # Connection error
    except Exception as excep:
        _LOGGER.exception("Unexpected exception checking charging options API: %s", excep)
        return False  # Unexpected error


class ChuckChargeBox:
    def __init__(
        self,
        hass: HomeAssistant,
        base_url,
        auth_name,
        auth_pass,
        have_net_current_sensor=False,
        phase_order=None,
        friendly_name=None,
    ) -> None:
        self.hass = hass
        self.base_url = base_url
        self._auth = (
            aiohttp.BasicAuth(auth_name, auth_pass)
            if auth_name and auth_pass
            else None
        )
        self.friendly_name = friendly_name
        self.status = {}
        self.basic_status = {}
        self.info = {}
        self.device_info = {}

        if phase_order is None:
            phase_order = [PHASE_ORDER_DICT_DEFAULT_CFG, PHASE_ORDER_DICT_DEFAULT_CFG]

        self.phase_order = [
            PHASE_ORDER.get(phase_order[0]),
            PHASE_ORDER.get(phase_order[1]),
        ]  # [conn1, conn2]

        self.have_net_current_sensor = have_net_current_sensor
        self.initializing = True
        self.tmp_charging_limit = [0, 0, 0, 0]

        self._session = async_get_clientsession(self.hass)

    async def _async_request(self, url: str, method: str = "GET", data: dict = None):
        """Make an API request."""
        _LOGGER.debug(f"request to {url} with data {data}")
        try:
            async with self._session.request(
                method, url, auth=self._auth, json=data, timeout=10
            ) as response:
                response.raise_for_status()
                return await response.json() if response.status != 204 else None # 204 no content
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                raise ChuckAuthError("Wrong username or password supplied for Chuck API") from e
            if e.status == 403:
                raise ChuckRestError("REST HTTP Error 403 - forbidden") from e
            _LOGGER.error(f"API request failed with status {e.status}: {e}")
            raise
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Error during API request: {e}")
            raise ChuckRestTimeout("Timeout reaching Chuck API") from e
        except Exception as e:
            _LOGGER.exception(f"Unexpected error: {e}")
            raise

    async def get_status(self):
        try:
            self.status = await self._async_request(
                f"{self.base_url}/api/admin/automation/status"
            )
        except Exception as e:
            _LOGGER.warning(
                "Unsucessful request for Chuck status: %s",
                e,
            )

    async def get_basic_status(self):
        try:
            self.basic_status = await self._async_request(f"{self.base_url}/api/status")
        except Exception as e:
            _LOGGER.warning(
                "Unsuccessful request for Chuck basic_status: %s",
                e,
            )

    async def get_info(self):
        try:
            self.info = await self._async_request(
                f"{self.base_url}/api/admin/automation/info"
            )
        except Exception as e:
            _LOGGER.warning(
                "Unsuccessful request for Chuck info: %s",
                e,
            )

    def get_friendly_name(self):
        if self.friendly_name is not None:
            return self.friendly_name
        else:
            return "Chargebox"

    async def send_command(self, url, data, auth=True):
        try:
            await self._async_request(url, method="POST", data=data)
        except Exception as e:
            _LOGGER.error(f"Failed to send command: {e}")
            raise

    def get_device_info(self):
        info = {
            "name": f"Chargebox {self.info['model']}",
            "manufacturer": self.info["vendor"],
            "model": self.info["model"],
            "identifiers": {(DOMAIN, self.info["serialNumber"])},
        }
        return info

    def get_connectors_count(self) -> int:
        try:
            return len(self.status.get("connectors", {}))
        except Exception as e:
            _LOGGER.warning(f"Error getting connectors count: {e}")
            return 0

    def get_connector_status(self, connector):
        try:
            return self.status.get("connectors", {}).get(str(connector), {}).get("status", "unknown")
        except Exception as e:
            _LOGGER.warning(f"Error getting status for connector {connector}: {e}")
            return "unknown"

    def get_connector_total_energy(self, connector):
        try:
            return self.status.get("connectors", {}).get(str(connector), {}).get("packet", {}).get("totalWh", 0)
        except Exception as e:
            _LOGGER.warning(f"Error getting total energy for connector {connector}: {e}")
            return 0

    def get_connector_session_energy(self, connector):
        try:
            return self.status.get("connectors", {}).get(str(connector), {}).get("packet", {}).get("actualWh", 0)
        except Exception as e:
            _LOGGER.warning(f"Error getting session energy for connector {connector}: {e}")
            return 0

    def get_phase_order_cfg(self):
        return self.phase_order

    def get_connector_voltage(self, connector):
        try:
            return self.status.get("connectors", {}).get(str(connector), {}).get("voltage", 0)
        except Exception as e:
            _LOGGER.warning(f"Error getting voltage for connector {connector}: {e}")
            return 0

    def get_connector_current(self, connector):
        try:
            return self.status.get("connectors", {}).get(str(connector), {}).get("current", 0)
        except Exception as e:
            _LOGGER.warning(f"Error getting current for connector {connector}: {e}")
            return 0

    def get_connector_power_kw(self, connector):
        return round(
            self.get_connector_current(connector)
            * self.get_connector_voltage(connector)
            / 1000,
            2,
        )

    def get_connector_max_charging_current(self, connector):
        try:
            return self.info.get("config", {}).get(f"MaxCurrent_{str(connector)}", 0)
        except Exception as e:
            _LOGGER.warning(f"Error getting max charging current for connector {connector}: {e}")
            return 0

    def get_connector_tmp_charging_limit(self, connector):
        return self.tmp_charging_limit[int(connector) - 1]

    def set_connector_tmp_charging_limit(self, connector, value):
        self.tmp_charging_limit[int(connector) - 1] = value

    async def set_connector_max_charging_current(self, connector, max_charging_current):
        _LOGGER.debug(f"SEND POST TO THIS CHARGER {connector}, {max_charging_current}")
        data = {
            "values": {f"MaxCurrent_{str(connector)}": str(max_charging_current)},
            "persist": False,
        }
        await self.send_command(f"{self.base_url}/api/admin/unitconfig", data)

    async def set_connector_enable_charging(self, connectorId: int, state: bool):
        _LOGGER.debug(f"Set connector {connectorId} to state {state}")
        data = {"connectorId": connectorId, "enable": state}
        await self.send_command(f"{self.base_url}/api/status", data)

    async def set_connector_charging_start(self, action: str, connector: int):
        data = {"action": action, "connector": connector}
        await self.send_command(f"{self.base_url}/api/transaction", data)

    def is_connector_charging_enabled(self, connectorId) -> bool:
        try:
            status = self.status.get("connectors", {}).get(str(connectorId), {}).get("status", "Unknown")
            return not status.startswith("Un")
        except Exception as e:
            _LOGGER.warning(f"Error checking if connector {connectorId} is enabled: {e}")
            return False

    def get_energy_total(self):
        energy_total = 0
        for c in range(0, self.get_connectors_count()):
            energy_total += self.get_connector_total_energy(c + 1)
        return energy_total

    def get_energy_session(self):
        energy_session = 0
        for c in range(0, self.get_connectors_count()):
            energy_session += self.get_connector_session_energy(c + 1)
        return energy_session

    def get_current_for_connector_L(self, connector, L):
        try:
            if not self.status.get("connectors") or not self.phase_order:
                return 0.0

            # Safe access to indices
            if int(connector) <= 0 or int(connector) > len(self.phase_order):
                return 0.0

            physical_L = self.phase_order[int(connector) - 1][L - 1]
            return float(
                self.status.get("connectors", {})
                .get(str(connector), {})
                .get("packet", {})
                .get("ext", {})
                .get(f"crrntl{str(physical_L)}", 0)
            )
        except Exception as e:
            _LOGGER.warning(f"Error getting current for connector {connector}, L{L}: {e}")
            return 0.0

    def get_net_current_for_L(self, L):
        try:
            physical_L = str(L)
            return self.status.get("connectors", {}).get("1", {}).get("packet", {}).get("ext", {}).get(
                f"exmcl{physical_L}", 0
            )
        except Exception as e:
            _LOGGER.warning(f"Error getting net current for L{L}: {e}")
            return 0

    def get_connector_charging_state(self, connector) -> str:
        try:
            return self.status.get("connectors", {}).get(str(connector), {}).get("packet", {}).get("chargingStatus", "UNKNOWN")
        except Exception as e:
            _LOGGER.warning(f"Error getting charging state for connector {connector}: {e}")
            return "UNKNOWN"

    def is_connector_charging(self, connector) -> bool:
        try:
            charging_state = self.get_connector_charging_state(connector)
            return charging_state.startswith("CHARGING") if charging_state else False
        except Exception as e:
            _LOGGER.warning(f"Error checking if connector {connector} is charging: {e}")
            return False

    def get_auth_status(self):
        return self.status.get("authTag")

    async def update(self) -> None:
        _LOGGER.debug("update all")
        await self.update_info()
        await self.update_status()
        if self.initializing:
            self.initializing = False
            if self.info and "config" in self.info: # Check if self.info and config exist
                default = self.info["config"].get("MaxDefaultCurrent", 0.0)
                self.tmp_charging_limit = [default, default, default, default]
            else:
                _LOGGER.warning("Could not retrieve config, setting default charging limit to 0")
                self.tmp_charging_limit = [0.0, 0.0, 0.0, 0.0] # if no config, default to 0

    async def update_info(self) -> None:
        await self.get_info()

    async def update_status(self) -> None:
        await self.get_status()


class ChuckRestTimeout(Exception):
    """Timeout from the API"""


class ChuckAuthError(Exception):
    """Chuck Auth error"""


class ChuckRestError(Exception):
    """Chuck Rest error"""

    def __init__(self, http_message) -> None:
        self.http_message = http_message


class ChuckCoordinatorEntity(CoordinatorEntity):
    """Base class for Chuck entities that use the coordinator."""

    def __init__(self, coordinator, chargebox):
        """Initialize the entity."""
        super().__init__(coordinator)
        self.chargebox = chargebox