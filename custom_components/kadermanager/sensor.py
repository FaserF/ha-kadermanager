from datetime import timedelta, datetime
import logging
from typing import Any, Dict, Optional
import requests
from bs4 import BeautifulSoup

import async_timeout

from homeassistant import config_entries, core
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util
import voluptuous as vol

from .const import CONF_TEAM_NAME, CONF_USERNAME, CONF_PASSWORD, ATTR_DATA, DOMAIN

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
        self.username = config.get(CONF_USERNAME)
        self.password = config.get(CONF_PASSWORD)
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
                login_url = f"https://{self.teamname}.kadermanager.de/sessions/new"
                # Check if username and password are provided
                if self.username and self.password:
                    _LOGGER.warning("Skipping login, since bot logins are blocked from website")
                else:
                    _LOGGER.debug("Username or password not provided, skipping login.")

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

    _LOGGER.debug(f"Fetched data: {str(soup)[:100]}")  # Log the first 100 characters for debugging

    events = []

    event_containers = soup.find_all('div', class_='event-detailed-container')
    for container in event_containers:
        _LOGGER.debug(f"Container: {container}")

        # Extract the event title
        event_title_element = container.find('a', class_='event-title-link')
        if event_title_element:
            event_title = event_title_element.text.strip()
        else:
            _LOGGER.debug(f"Event title link not found, container: {container}")
            event_title = "Unknown"

        # Find the element with class 'circle-in-enrollments'
        circle_in_enrollments = container.find_all('div', class_='circle-in-enrollments')
        _LOGGER.debug(f"Searching in_count in: {circle_in_enrollments}")
        # Check if the element is found and extract the text
        if circle_in_enrollments:
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

        # Remove the day of the week from the date
        event_date_parts = event_date.split()
        if len(event_date_parts) > 1:
            event_date = event_date_parts[1]
        else:
            event_date = event_date_parts[0]

        # Ensure the date has no additional periods
        if event_date.endswith('.'):
            event_date = event_date[:-1]

        # Add the current year to the event date if not already present
        current_year = datetime.now().year
        event_date += f".{current_year}"

        # Parse the date using multiple formats
        event_date_iso = None
        for date_format in ["%d.%m.%Y"]:
            try:
                event_date_parsed = datetime.strptime(event_date, date_format)
                event_date_iso = event_date_parsed.date().isoformat()
                _LOGGER.debug(f"Successfully parsed date '{event_date}' as '{event_date_iso}'")
                break
            except ValueError as ve:
                _LOGGER.debug(f"Failed to parse date '{event_date}' with format '{date_format}': {ve}")
                continue

        if event_date_iso is None:
            _LOGGER.error(f"Error parsing date: {event_date}")
            event_date_iso = "Unknown"

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

def login_and_fetch_data(username, password, login_url, URL):
    # Define headers with a fake user agent
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }

    with requests.Session() as session:
        # Try signing in with provided login credentials
        login_data = {
            'login_name': username,
            'password': password
        }

        # Send a GET request to the login page to get the CSRF token
        login_response = session.get(login_url, headers=headers)
        soup = BeautifulSoup(login_response.content, 'html.parser')
        csrf_token = soup.find('input', {'name': 'authenticity_token'})['value']
        login_data['authenticity_token'] = csrf_token

        # Send a POST request with login data
        post = session.post(login_url, data=login_data, headers=headers)

        # Check login for success
        if post.status_code == 200:
            _LOGGER.debug(f"Login successful: {login_url}")
            response = session.get(URL, headers=headers)
            soup = BeautifulSoup(response.content, 'html.parser')
            # Now you can continue to scrape the data from the page
        else:
            _LOGGER.error(f"Login failed: {login_url} - Username: {username} - Status: {post.status_code} - Some attribute informations won't be available.")
            _LOGGER.debug(f"Login response: {post.text}")

def setup_platform(hass, config, add_entities, discovery_info=None):
    add_entities([KadermanagerSensor(config, hass)])
