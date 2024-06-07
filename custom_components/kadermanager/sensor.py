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

                # Login URL
                login_url = f"https://{self.teamname}.kadermanager.de/sessions/new"
                """Pull data from the kadermanager.de web page."""
                _LOGGER.debug(f"Update the connection data for '{self.teamname}'")
                events = await self.hass.async_add_executor_job(get_kadermanager_events, URL)
                if events:
                    limited_events = events[:5]  # Limit to the next 5 events
                    self._state = limited_events[0]['original_date']
                    self._attributes = {
                        'events': limited_events
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
        _LOGGER.debug(f"Container: {container}")
        # Find the element with class 'circle-in-enrollments'
        circle_in_enrollments = container.find('div', class_='circle-in-enrollments')
        # Check if the element is found and extract the text
        if circle_in_enrollments:
            _LOGGER.debug(f"Extracted in_count text: {circle_in_enrollments}")
            in_count = circle_in_enrollments.text.strip()
        else:
            in_count = "Unknown"

        # Convert in_count to an integer if possible
        try:
            in_count = int(in_count)
        except ValueError:
            _LOGGER.error(f"Error parsing in_count: {in_count}")
            in_count = 0

        _LOGGER.debug(f"In count: {in_count}")

        event_link_elements = container.find_all('a', href=True)  # Find all <a> tags with href attribute
        event_url = None
        for event_link_element in event_link_elements:
            if "player" not in event_link_element['href']:
                event_url = event_link_element['href']
                break

        if not event_url:
            event_url = url  # Use the main URL as a default link if no suitable link is found

        event_date_element = container.find('h4')
        event_date_time = event_date_element.text.strip() if event_date_element else "Unknown"

        # Split event_date_time into date and time
        if ' um ' in event_date_time:
            event_date, event_time = event_date_time.split(' um ')
        else:
            event_date = event_date_time
            event_time = "Unknown"

        # Parse the date using multiple formats
        event_date_iso = None
        for date_format in ["%a %d.%m.", "%a %d.%m", "%a %d.%m.%Y"]:
            try:
                day, month = event_date.split()
                month_int = datetime.strptime(month, "%b").month
                event_date_converted = datetime(datetime.now().year, month_int, int(day))
                event_date_iso = event_date_converted.date().isoformat()
                break
            except ValueError:
                continue

        if event_date_iso is None:
            _LOGGER.error(f"Error parsing date: {event_date}")
            event_date_iso = "Unknown"

        # Extract the title correctly
        event_title_element = container.find_next_sibling('div', class_='span4 event-image-container')
        if event_title_element:
            event_title_span = event_title_element.find('span', class_='event-name-information')
            event_title = event_title_span.text.strip() if event_title_span else "Unknown"
        else:
            event_title = "Unknown"

        _LOGGER.debug(f"Fetched informations: {event_title} - {event_url} - {event_date} - {in_count}")

        event_info = {
            'original_date': event_date_time.replace(" um ", " "),
            'date': event_date_iso,
            'time': event_time,
            'in_count': in_count,
            'title': event_title,
            'link': event_url,
        }
        events.append(event_info)

    return events

def setup_platform(hass, config, add_entities, discovery_info=None):
    add_entities([KadermanagerSensor(config, hass)])
