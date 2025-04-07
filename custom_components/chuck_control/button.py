from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant import config_entries, core
from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
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
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    charger_connected_to_ocpp = config_entry.options.get("is_connected_to_ocpp", False)
    to_add = get_buttons_to_add(chargebox, coordinator, charger_connected_to_ocpp)
    async_add_entities(to_add)


def get_buttons_to_add(
    chargebox, coordinator, charger_connected_to_ocpp
) -> list[ButtonEntity]:
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
        connector_id = connector + 1
        if charger_connected_to_ocpp:
            buttons_to_add.append(
                StartTransactionButton(
                    chargebox=chargebox,
                    coordinator=coordinator, # Pass coordinator
                    connector_id=connector_id,
                )
            )

        buttons_to_add.extend(
            [
                EnableChargingButton(
                    chargebox=chargebox,
                    coordinator=coordinator, # Pass coordinator
                    connector_id=connector_id,
                ),
                DisableChargingButton(
                    chargebox=chargebox,
                    coordinator=coordinator, # Pass coordinator
                    connector_id=connector_id,
                ),
            ]
        )
    return buttons_to_add


# --- Base Button Class (Optional Refactor) ---
# You could create a base class to avoid repeating __init__ logic
class BaseChuckButton(ButtonEntity):
    _attr_has_entity_name = True # Usually True for buttons unless name is set explicitly

    def __init__(self, chargebox, coordinator, connector_id) -> None:
        """Initialize the button."""
        super().__init__()
        self.chargebox = chargebox
        self.coordinator = coordinator # Store coordinator
        self.connector_id = connector_id
        self._attr_device_info = self.chargebox.get_device_info() # Set attribute directly

    async def _async_press_action(self, *args, **kwargs):
        """Placeholder for the actual action. Should be overridden."""
        raise NotImplementedError

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self._async_press_action()
            # Request a refresh after the action is successful
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(
                "Error pressing button %s: %s", self.entity_id or self.unique_id, e
            )


# --- Specific Button Implementations ---

class DisableChargingButton(BaseChuckButton): # Inherit from BaseChuckButton
    def __init__(self, chargebox, coordinator, connector_id) -> None:
        super().__init__(chargebox, coordinator, connector_id) # Call parent init
        # self.friendly_name_appendix = "Disable charging" # Use _attr_name instead
        # self.friendly_name = get_friendly_name(self) # Use _attr_name instead
        self._attr_name = f"{get_friendly_name(self, phase=False)} Disable charging" # Set name attribute
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_disable_charging" # Set unique_id attribute
        self._attr_icon = "mdi:stop-circle-outline" # Suggest an icon

    async def _async_press_action(self): # Implement specific action
        """Disable charging for the connector."""
        await self.chargebox.set_connector_enable_charging(
            connectorId=self.connector_id, state=False
        )

    # Properties unique_id, name, device_info are handled by base class or attributes


class EnableChargingButton(BaseChuckButton): # Inherit from BaseChuckButton
    def __init__(self, chargebox, coordinator, connector_id) -> None:
        super().__init__(chargebox, coordinator, connector_id) # Call parent init
        # self.friendly_name_appendix = "Enable charging"
        # self.friendly_name = get_friendly_name(self)
        self._attr_name = f"{get_friendly_name(self, phase=False)} Enable charging" # Set name attribute
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_enable_charging" # Set unique_id attribute
        self._attr_icon = "mdi:play-circle-outline" # Suggest an icon

    async def _async_press_action(self): # Implement specific action
        """Enable charging for the connector."""
        await self.chargebox.set_connector_enable_charging(
            connectorId=self.connector_id, state=True
        )

    # Properties unique_id, name, device_info are handled by base class or attributes


class StartTransactionButton(BaseChuckButton): # Inherit from BaseChuckButton
    def __init__(self, chargebox, coordinator, connector_id) -> None:
        super().__init__(chargebox, coordinator, connector_id) # Call parent init
        # self.friendly_name_appendix = "Start transcation"
        # self.friendly_name = get_friendly_name(self)
        self._attr_name = f"{get_friendly_name(self, phase=False)} Start Transaction" # Set name attribute
        self._attr_unique_id = f"{self.chargebox.info['serialNumber']}_connector_{self.connector_id}_transcation_start" # Set unique_id attribute
        self._attr_icon = "mdi:play-box-outline" # Suggest an icon


    async def _async_press_action(self): # Implement specific action
        """Start a charging transaction (for OCPP mode)."""
        # Assuming 'Start' is the correct action string for your API
        await self.chargebox.set_connector_charging_start(
            action="Start", connector=self.connector_id
        )

    # Properties unique_id, name, device_info are handled by base class or attributes
