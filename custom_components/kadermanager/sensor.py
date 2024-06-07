"""kadermanager sensor platform."""
from datetime import timedelta, datetime
import logging
from typing import Any, Callable, Dict, Optional
import requests
from bs4 import BeautifulSoup

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
SCAN_INTERVAL = timedelta(minutes=30)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigType, async_add_entities: AddEntitiesCallback
):
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.debug("Sensor async_setup_entry")
    if entry.options:
        config.update(entry.options)
    async_add_entities(
        [
            KadermanagerSensor(config, hass)
        ],
        update_before_add=True
    )

class KadermanagerSensor(SensorEntity):
    """Implementation of a Kadermanager sensor."""

    def __init__(self, config, hass: HomeAssistant):
        super().__init__()
        self._name = f"kadermanager_{config[CONF_TEAM_NAME]}"
        self.teamname = config[CONF_TEAM_NAME]
        self._state = None
        self._available = True
        self.hass = hass
        self.updated = datetime.now()
        self._attributes = {}

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._name

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
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    async def async_update(self):
        try:
            with async_timeout.timeout(30):
                URL = f"https://{self.teamname}.kadermanager.de/events"
                """Pull data from the kadermanager.de web page."""
                _LOGGER.debug(f"Update the connection data for '{self.teamname}'")
                events = await self.hass.async_add_executor_job(get_kadermanager_events, URL)
                if events:
                    self._state = events[0]['date']
                    self._attributes = {
                        'location': events[0].get('location', 'Unknown'),
                        'in_count': events[0]['in_count'],
                        'out_count': events[0].get('out_count', 'Unknown'),
                        'title': events[0]['title'],
                        'link': events[0]['link'],
                    }
                else:
                    self._state = "No events found"
                    self._attributes = {}
        except Exception as e:
            self._available = False
            _LOGGER.error(f"Error fetching data from Kadermanager: {e}")

def get_kadermanager_events(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    _LOGGER.debug(f"Fetched data: {response.text[:1000]}")  # Log the first 1000 characters for debugging

    events = []

    event_containers = soup.find_all('div', class_='event-information-container')
    for container in event_containers:
        event_link_element = container.find('a', href=True)
        if not event_link_element:
            continue

        event_url = event_link_element['href']
        event_date_element = container.find('h4')
        event_date = event_date_element.text.strip() if event_date_element else "Unknown"

        in_count_element = container.find('div', class_='circle-in-enrollments')
        in_count = int(in_count_element.text.strip()) if in_count_element else 0

        response_event = requests.get(event_url)
        soup_event = BeautifulSoup(response_event.text, 'html.parser')

        out_link = soup_event.find('a', href=True, text=lambda x: x and 'Out' in x)
        out_count = int(out_link.text.split()[-1]) if out_link else 0

        event_location_element = container.find('div', class_='event-location')
        event_location = event_location_element.text.strip() if event_location_element else "Unknown"

        event_title_element = container.find_next_sibling('div', class_='event-name-information')
        event_title = event_title_element.text.strip() if event_title_element else "Unknown"

        _LOGGER.debug(f"Fetched informations: {event_title} - {event_url} - {event_date} - {event_location} - In: {in_count} - Out: {out_count}")

        event_info = {
            'date': event_date,
            'location': event_location, # Location is not available in unauthenticated response
            'in_count': in_count,
            'out_count': out_count, # Out Count is not available in unauthenticated response
            'title': event_title,
            'link': event_url,
        }
        events.append(event_info)

    return events

def setup_platform(hass, config, add_entities, discovery_info=None):
    add_entities([KadermanagerSensor(config, hass)])
