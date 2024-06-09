from datetime import datetime, timedelta
import logging
import requests
from bs4 import BeautifulSoup
import async_timeout
from typing import Optional, List, Dict
from homeassistant import config_entries, core
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util
import voluptuous as vol
from .const import CONF_TEAM_NAME, CONF_USERNAME, CONF_PASSWORD, ATTR_DATA, DOMAIN, CONF_UPDATE_INTERVAL
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry, async_add_entities: AddEntitiesCallback
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
        self._name = f"Kadermanager {config[CONF_TEAM_NAME]}"
        self.teamname = config[CONF_TEAM_NAME]
        self.username = config.get(CONF_USERNAME)
        self.password = config.get(CONF_PASSWORD)
        self.update_interval = timedelta(minutes=config.get(CONF_UPDATE_INTERVAL, 30))
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
                main_url = f"https://{self.teamname}.kadermanager.de"
                # Check if username and password are provided
                if self.username and self.password:
                    _LOGGER.warning("Skipping login, since bot logins are blocked from website")
                else:
                    _LOGGER.debug("Username or password not provided, skipping login.")

                """Pull data from the kadermanager.de web page."""
                _LOGGER.debug(f"Update the connection data for '{self.teamname}'")
                events = await self.hass.async_add_executor_job(get_kadermanager_events, URL, main_url)
                if events:
                    limited_events = events[:5]  # Limit to the next 5 events
                    self._state = limited_events[0]['original_date']
                    self._attributes = {
                        'events': limited_events,
                        'last_updated': datetime.now().isoformat()
                    }
                else:
                    self._state = "No events found"
                    self._attributes = {}
        except Exception as e:
            self._available = False
            _LOGGER.error(f"Error fetching data from Kadermanager: {e}")

    @property
    def should_poll(self):
        """Return the polling state."""
        return True

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self.async_update, self.update_interval
            )
        )

def get_kadermanager_events(url, main_url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    _LOGGER.debug(f"Fetched data: {str(soup)[:20000]}")  # Log the first characters for debugging

    main_response = requests.get(main_url)
    main_soup = BeautifulSoup(main_response.text, 'html.parser')

    events = []

    event_containers = soup.find_all('div', class_='event-detailed-container')
    main_event_containers = main_soup.find_all('div', class_='circle-in-enrollments')

    for idx, container in enumerate(event_containers):
        _LOGGER.debug(f"Container: {container}")

        # Extract the event title
        event_title_element = container.find('a', class_='event-title-link')
        if event_title_element:
            event_title = event_title_element.text.strip()
        else:
            _LOGGER.debug(f"Event title link not found, container: {container}")
            event_title = "Unknown"

        # Set in_count based on index
        if idx < 2:
            if main_event_containers:
                in_count_element = main_event_containers[idx]
                in_count = in_count_element.text.strip() if in_count_element else "Unknown"
                # Convert in_count to an integer if possible
                try:
                    in_count = int(in_count)
                except ValueError:
                    _LOGGER.error(f"Error parsing in_count: {in_count}")
                    in_count = 0
            else:
                in_count = "Unknown"
        else:
            in_count = "Unknown"

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

        # Determine the correct year for the event date
        current_year = datetime.now().year
        if '.' in event_date:
            # Check if the year is already in the date
            if len(event_date.split('.')) == 3:
                event_date_with_year = event_date
            else:
                event_date_with_year = f"{event_date}.{current_year}"
        else:
            event_date_with_year = f"{event_date}.{current_year}"

        # Parse the date using multiple formats
        event_date_iso = None
        try:
            event_date_parsed = datetime.strptime(event_date_with_year, "%d.%m.%Y")
            if event_date_parsed < datetime.now():
                event_date_parsed = event_date_parsed.replace(year=current_year + 1)
            event_date_iso = event_date_parsed.date().isoformat()
            _LOGGER.debug(f"Successfully parsed date '{event_date_with_year}' as '{event_date_iso}'")
        except ValueError as ve:
            _LOGGER.error(f"Error parsing date: {event_date_with_year} with error: {ve}")
            event_date_iso = "Unknown"

        # Extract location
        event_location_element = container.find('div', text=lambda x: x and 'Am Sportpark' in x)
        event_location = event_location_element.text.strip() if event_location_element else "Unknown"

        _LOGGER.debug(f"Fetched information: {event_title} - {event_url} - {event_date_iso} - {in_count} - {event_location}")

        event_type = None
        for possible_type in ["Training", "Spiel", "Sonstiges"]:
            if possible_type in event_title:
                event_type = possible_type
                event_title = event_title.replace(possible_type, "").replace(" · ", "").strip()
                break

        if event_type is None:
            event_type = "Unknown"

        event_info = {
            'original_date': event_date_time.replace(" um ", " "),
            'date': event_date_iso,
            'time': event_time,
            'in_count': in_count,
            'title': event_title,
            'link': event_url,
            'location': event_location,
            'type': event_type
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
