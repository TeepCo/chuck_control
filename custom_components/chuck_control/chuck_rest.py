import json

from . import DOMAIN
from .const import PHASE_ORDER_DICT, PHASE_ORDER_DICT_DEFAULT_CFG, PHASE_ORDER

import requests
from requests.auth import HTTPBasicAuth
import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost/"
DEFAULT_AUTH_NAME = "admin"
DEFAULT_AUTH_PASS = "admin"


async def test_connection(
    hass: HomeAssistant, baseurl: str, username: str, password: str
):
    """Requests data from uri supplied"""

    url = baseurl + "/api/admin/automation/status"

    _LOGGER.debug(f"request to {url}")
    timeout = 60
    try:
        if username and password:
            response = await hass.async_add_executor_job(
                requests.get(
                    url,
                    auth=HTTPBasicAuth(username, password),
                    timeout=timeout,
                )
            )
        else:
            response = await hass.async_add_executor_job(
                requests.get(url, timeout=timeout)
            )

    except requests.exceptions.Timeout as exception:
        raise ChuckRestTimeout("Timeout reaching Chuck API") from exception

    if response.status_code == 401:
        raise ChuckAuthError("Wrong username or password supplied for Chuck API")

    return bool(response.status_code == 200)


class ChuckChargeBox:
    def __init__(
        self,
        hass: HomeAssistant,
        base_url=DEFAULT_BASE_URL,
        auth_name=DEFAULT_AUTH_NAME,
        auth_pass=DEFAULT_AUTH_PASS,
        have_net_current_sensor=False,
        phase_order=None,
        friendly_name=None,
    ) -> None:
        self.hass = hass
        self.base_url = base_url
        self.auth_name = auth_name
        self.auth_pass = auth_pass
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

    def request_data(self, url):
        """Requests data from uri supplied"""

        _LOGGER.debug(f"request to {url}")
        timeout = 60
        try:
            if self.auth_name and self.auth_pass:
                response = requests.get(
                    url,
                    auth=HTTPBasicAuth(self.auth_name, self.auth_pass),
                    timeout=timeout,
                )
            else:
                response = requests.get(url, timeout=timeout)
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exception:
            raise ChuckRestTimeout("Timeout reaching Chuck API") from exception

        if response.status_code == 401:
            raise ChuckAuthError("Wrong username or password supplied for Chuck API")

        if response.status_code == 403:
            raise ChuckRestError("REST HTTP Error 403 - forbidden")
        return response

    def get_status(self):
        response = self.request_data(f"{self.base_url}/api/admin/automation/status")
        if response.status_code == 200:
            self.status = response.json()
        else:
            _LOGGER.warning(
                "Unsucessful request for Chuck info, response=%s to url=%s",
                response.status_code,
                response.url,
            )

    def get_basic_status(self):
        response = self.request_data(f"{self.base_url}/api/status")
        if response.status_code == 200:
            self.basic_status = response.json()

    def get_info(self):
        response = self.request_data(f"{self.base_url}/api/admin/automation/info")
        if response.status_code == 200:
            self.info = response.json()
        else:
            _LOGGER.warning(
                "Unsucessful request for Chuck info, response=%s to url=%s",
                response.status_code,
                response.url,
            )

    def get_friendly_name(self):
        if self.friendly_name is not None:
            return self.friendly_name
        else:
            return "Chargebox"

    async def send_command(self, url, data, auth=True):
        await self.hass.async_add_executor_job(self.send_post, url, data, auth)

    def send_post(self, url, data, auth):
        _LOGGER.debug(f"SEND COMMAND {url}, {data}")
        if auth:
            _LOGGER.debug("AUTH")
            requests.post(
                url, json=data, auth=(self.auth_name, self.auth_pass), timeout=5
            )
        else:
            _LOGGER.debug("NO AUTH")
            requests.post(url, json=data, timeout=5)

    def get_device_info(self):
        info = {
            "name": f"Chargebox {self.info['model']}",
            "manufacturer": self.info["vendor"],
            "model": self.info["model"],
            "identifiers": {(DOMAIN, self.info["serialNumber"])},
        }
        return info

    def get_connectors_count(self) -> int:
        return len(self.status["connectors"])

    def get_connector_status(self, connector):
        return self.status["connectors"][str(connector)]["status"]

    def get_connector_total_energy(self, connector):
        return self.status["connectors"][str(connector)]["packet"]["totalWh"]

    def get_connector_session_energy(self, connector):
        return self.status["connectors"][str(connector)]["packet"]["actualWh"]

    def get_phase_order_cfg(self):
        return self.phase_order

    def get_connector_voltage(self, connector):
        return self.status["connectors"][str(connector)]["voltage"]

    def get_connector_current(self, connector):
        return self.status["connectors"][str(connector)]["current"]

    def get_connector_power_kw(self, connector):
        return round(
            self.get_connector_current(connector)
            * self.get_connector_voltage(connector)
            / 1000,
            2,
        )

    def get_connector_max_charging_current(self, connector):
        return self.info["config"][f"MaxCurrent_{str(connector)}"]

    def get_connector_tmp_charging_limit(self, connector):
        return self.tmp_charging_limit[int(connector) - 1]

    def set_connector_tmp_charging_limit(self, connector, value):
        self.tmp_charging_limit[int(connector) - 1] = value

    async def set_connector_max_charging_current(self, connector, max_charging_current):
        _LOGGER.debug(f"SEND POST TO THIS CHARGER {connector}, {max_charging_current}")
        data = {"values": {f"MaxCurrent_{str(connector)}": str(max_charging_current)}}
        await self.send_command(f"{self.base_url}/api/admin/unitconfig", data)

    async def set_connector_enable_charging(self, connectorId: int, state: bool):
        _LOGGER.debug(f"Set connector {connectorId} to state {state}")
        data = {"connectorId": connectorId, "enable": state}
        await self.send_command(f"{self.base_url}/api/status", data)

    async def set_connector_charging_start(self, action: str, connector: int):
        data = {"action": action, "connector": connector}
        await self.send_command(f"{self.base_url}/api/transaction", data)

    def is_connector_charging_enabled(self, connectorId) -> bool:
        return not self.status["connectors"][str(connectorId)]["status"].startswith(
            "Un"
        )

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
        physical_L = self.phase_order[int(connector) - 1][L - 1]
        return self.status["connectors"][str(connector)]["packet"]["ext"][
            f"crrntl{str(physical_L)}"
        ]

    def get_net_current_for_L(self, L):
        physical_L = str(L)
        return self.status["connectors"]["1"]["packet"]["ext"].get(
            f"exmcl{physical_L}", 0
        )

    def get_connector_charging_state(self, connector) -> str:
        return self.status["connectors"][str(connector)]["packet"]["chargingStatus"]

    def is_connector_charging(self, connector) -> bool:
        return self.get_connector_charging_state(connector).startswith("CHARGING")

    def get_auth_status(self):
        return self.status.get("authTag")

    def update(self) -> None:
        _LOGGER.debug("update all")
        self.update_info()
        self.update_status()
        if self.initializing:
            self.initializing = False
            default = self.info["config"].get("MaxDefaultCurrent", 0.0)
            self.tmp_charging_limit = [default, default, default, default]

    def update_info(self) -> None:
        self.get_info()

    def update_status(self) -> None:
        self.get_status()


class ChuckRestTimeout(Exception):
    """Timeout from the API"""


class ChuckAuthError(Exception):
    """Chuck Auth error"""


class ChuckRestError(Exception):
    """Chuck Rest error"""

    def __init__(self, http_message) -> None:
        self.http_message = http_message
