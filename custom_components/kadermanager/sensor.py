import logging
from typing import Optional, Any
from datetime import datetime

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_TEAM_NAME
from .coordinator import KadermanagerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Setup sensors from a config entry created in the integrations UI."""
    coordinator: KadermanagerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KadermanagerSensor(coordinator, entry)], update_before_add=True)

class KadermanagerSensor(CoordinatorEntity, SensorEntity):
    """Implementation of a Kadermanager sensor."""

    def __init__(self, coordinator: KadermanagerDataUpdateCoordinator, entry: config_entries.ConfigEntry):
        super().__init__(coordinator)
        self.teamname = entry.data[CONF_TEAM_NAME]
        self._name = f"Kadermanager {self.teamname}"
        self._entry_id = entry.entry_id

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self) -> str:
        return f"{self.teamname}_sensor"

    @property
    def icon(self):
        return "mdi:volleyball"

    @property
    def state(self) -> Optional[str]:
        if not self.coordinator.data or not self.coordinator.data.get('events'):
            return "No events found"
        return self.coordinator.data['events'][0]['original_date']

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data:
            return {}

        attrs = {
            'events': self.coordinator.data.get('events', []),
            'last_updated': datetime.now().isoformat()
        }
        if 'general_comments' in self.coordinator.data:
             attrs['comments'] = self.coordinator.data['general_comments']

        return attrs

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def attribution(self):
        from .const import ATTRIBUTION
        return ATTRIBUTION

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self.teamname)},
            "name": f"Kadermanager {self.teamname}",
            "manufacturer": "Kadermanager",
            "model": "Team Schedule",
            "configuration_url": f"https://{self.teamname}.kadermanager.de",
        }
