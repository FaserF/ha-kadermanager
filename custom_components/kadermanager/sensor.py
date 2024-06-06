"""kadermanager sensor platform."""
from datetime import timedelta, datetime
import logging
from typing import Any, Callable, Dict, Optional, Set
import re

import async_timeout

from homeassistant import config_entries, core
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import (
    ConfigType,
    DiscoveryInfoType,
)
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util
import voluptuous as vol

from .const import (
    CONF_TEAM_NAME,
    ATTR_DATA,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=2)
URL = f"'https://' + {config[CONF_TEAM_NAME]} + '.kadermanager.de/events'"

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigType, async_add_entities
):
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.debug("Sensor async_setup_entry")
    if entry.options:
        config.update(entry.options)
    sensors = KadermanagerSensor(config, hass)
    async_add_entities(
        [
            KadermanagerSensor(config, hass)
        ],
        update_before_add=True
    )

class KadermanagerSensor(SensorEntity):
    """Implementation of a Deutsche Bahn sensor."""

    def __init__(self, config, hass: HomeAssistant):
        super().__init__()
        self._name = f"{config[CONF_TEAM_NAME]}"
        self._state = None
        self._available = True
        self.hass = hass
        self.updated = datetime.now()

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._name
        #return f"{self.start}_{self.goal}"

    @property
    def icon(self):
        """Return the icon for the frontend."""
        return "mdi:volleyball"

    @property
    def state(self) -> Optional[str]:
        if self._state is not None:
            return self._state
        else:
            return "Unknown"

    @property
    def native_value(self):
        """Return the kadermanager informations."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if len(self.connections) > 0:
            connections = self.connections[0].copy()
            for cons in range(1,len(self.connections)):
                if len(self.connections) > cons:
                    connections[f"next_{cons}"] = self.connections[cons]["departure"]
                    connections[f"next_{cons}_delay"] = self.connections[cons]["delay"]
                    connections[f"next_{cons}_canceled"] = self.connections[cons]["canceled"]
                    connections[f"next_{cons}_arrival"] = self.connections[cons]["arrival"]
        else:
            connections = None
        connections["departures"] = self.connections
        return connections

    async def async_update(self):
        try:
            with async_timeout.timeout(30):
                hass = self.hass
                """Pull data from the kadermanager.de web page."""
                _LOGGER.debug(f"Update the connection data for '{config[CONF_TEAM_NAME]}'")
                events = await hass.async_add_executor_job(
                        get_kadermanager_events(URL)
                    )
                if events:
                    self._state = events[0]['date']
                    self._attributes = {
                        'location': events[0]['location'],
                        'in_count': events[0]['in_count'],
                        'out_count': events[0]['out_count'],
                    }
        except:
            self._available = False
            _LOGGER.error(f"Error fetching data from Kadermanager: {e}")

def get_kadermanager_events(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    events = []

    event_links = soup.find_all('a', href=True, style="color: inherit;")
    for link in event_links:
        event_url = link['href']
        event_date = link.find('h4').text.strip()
        event_location = link.find('div').text.strip()

        response_event = requests.get(event_url)
        soup_event = BeautifulSoup(response_event.text, 'html.parser')

        in_count = int(soup_event.find('a', href=lambda x: x and 'tab_in' in x).text.split()[-1])
        out_count = int(soup_event.find('a', href=lambda x: x and 'tab_out' in x).text.split()[-1])

        event_info = {
            'date': event_date,
            'location': event_location,
            'in_count': in_count,
            'out_count': out_count,
        }
        events.append(event_info)

    return events

def setup_platform(hass, config, add_entities, discovery_info=None):
    add_entities([KadermanagerSensor()])