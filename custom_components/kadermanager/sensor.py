import logging
import requests
import voluptuous as vol
import async_timeout
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from homeassistant import config_entries, core
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import issue_registry as ir
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_EVENT_LIMIT,
    CONF_FETCH_COMMENTS,
    CONF_FETCH_PLAYER_INFO,
    CONF_PASSWORD,
    CONF_TEAM_NAME,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
REQUEST_TIMEOUT = 15  # seconds
ISSUE_ID_CONNECTION = "connection_error"

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
        self.event_limit = config.get(CONF_EVENT_LIMIT, 5)
        self.fetch_player_info = config.get(CONF_FETCH_PLAYER_INFO, False)
        self.fetch_comments = config.get(CONF_FETCH_COMMENTS, False)
        self._state = None
        self._available = True
        self.hass = hass
        self._attributes = {}

        # Repair logic tracking
        self._last_success: Optional[datetime] = datetime.now()
        self._issue_created = False

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self) -> str:
        return self._name

    @property
    def icon(self):
        return "mdi:volleyball"

    @property
    def state(self) -> Optional[str]:
        return self._state if self._state is not None else "Unknown"

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def available(self) -> bool:
        return self._available

    async def async_update(self):
        """Get the latest data."""
        try:
            with async_timeout.timeout(45):
                URL = f"https://{self.teamname}.kadermanager.de/events"
                main_url = f"https://{self.teamname}.kadermanager.de"
                login_url = f"https://{self.teamname}.kadermanager.de/sessions/new"

                events = await self.hass.async_add_executor_job(
                    self._scrape_data, URL, main_url, login_url
                )

                if events:
                    self._state = events[0]['original_date']
                    self._attributes.update({
                        'events': events,
                        'last_updated': datetime.now().isoformat()
                    })
                    self._available = True
                    self._last_success = datetime.now()

                    # Clear repair issue if it exists
                    if self._issue_created:
                        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID_CONNECTION)
                        self._issue_created = False
                else:
                    _LOGGER.info("No events found or scraping failed.")
                    if self._state is None:
                         self._state = "No events found"
                    self._attributes = {}

        except Exception as e:
            self._available = False
            _LOGGER.error(f"Error fetching data from Kadermanager: {e}")

            # Check for repair trigger
            if self._last_success and (datetime.now() - self._last_success) > timedelta(hours=24):
                if not self._issue_created:
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        ISSUE_ID_CONNECTION,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="connection_error",
                        learn_more_url="https://github.com/FaserF/ha-kadermanager/issues"
                    )
                    self._issue_created = True

    def _scrape_data(self, url: str, main_url: str, login_url: str) -> List[Dict[str, Any]]:
        """Synchronous scraping job."""
        session = requests.Session()
        session.headers.update({'User-Agent': USER_AGENT})

        # Login if credentials provided
        if self.username and self.password:
            _login(session, login_url, self.username, self.password)

        # Fetch events
        events = get_kadermanager_events(session, url, main_url)

        limited_events = events[:self.event_limit]

        for event in limited_events:
            event['players'] = {}
            event['comments'] = []

            if self.fetch_player_info:
                event_url = event.get('link')
                if event_url and event_url != url:
                    players = get_players_for_event(session, event_url)
                    event['players'] = players

                    if self.fetch_comments:
                        comments = get_comments_for_event(session, event_url)
                        event['comments'] = comments

        if self.fetch_comments:
             general_comments = get_general_comments(session, main_url)
             self._attributes['comments'] = general_comments

        return limited_events

    @property
    def should_poll(self):
        return True

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self.async_update,
                self.update_interval
            )
        )

def _login(session: requests.Session, login_url: str, username: str, password: str):
    """Perform login."""
    try:
        _LOGGER.debug(f"Accessing login page: {login_url}")
        r_get = session.get(login_url, timeout=REQUEST_TIMEOUT)
        r_get.raise_for_status()

        soup = BeautifulSoup(r_get.text, 'html.parser')

        token_input = soup.find('input', {'name': 'authenticity_token'})
        if not token_input:
            _LOGGER.warning("Could not find authenticity_token on login page. Login may fail.")
            token = ""
        else:
            token = token_input.get('value')

        payload = {
            'authenticity_token': token,
            'login_name': username,
            'password': password,
        }

        form = soup.find('form', id='login_form')
        if not form:
            form = soup.find('form', action=lambda x: x and 'sessions' in x)

        post_url = login_url
        if form and form.get('action'):
            action = form.get('action')
            if action.startswith('http'):
                post_url = action
            else:
                from urllib.parse import urljoin
                post_url = urljoin(login_url, action)

        _LOGGER.debug(f"Posting login to {post_url}")
        r_post = session.post(post_url, data=payload, timeout=REQUEST_TIMEOUT)

        if r_post.status_code == 200:
            if "Invalid login" in r_post.text or "Anmeldung fehlgeschlagen" in r_post.text:
                _LOGGER.error("Login failed (invalid credentials?). Continuing as guest.")
            else:
                _LOGGER.debug("Login successful (session cookies set).")
        else:
             _LOGGER.warning(f"Login POST returned status {r_post.status_code}")

    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")

def _get_soup(session: requests.Session, url: str) -> Optional[BeautifulSoup]:
    """Helper to fetch a URL and return BeautifulSoup object."""
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        _LOGGER.error(f"Failed to fetch {url}: {e}")
        return None

def get_players_for_event(session: requests.Session, event_url: str) -> Dict[str, List[str]]:
    soup = _get_soup(session, event_url)
    player_types = {
        'accepted_players': [],
        'declined_players': [],
        'no_response_players': []
    }
    if not soup:
        return player_types

    drop_zones = soup.find_all('div', class_='drop-zone')
    for zone in drop_zones:
        zone_id = zone.get('id')
        players = []
        player_labels = zone.find_all('span', class_='player_label')
        for label in player_labels:
            players.append(label.text.strip())

        if zone_id == 'zone_1':
            player_types['accepted_players'] = players
        elif zone_id == 'zone_2':
            player_types['declined_players'] = players
        elif zone_id == 'zone_3':
            player_types['no_response_players'] = players

    return player_types

def get_comments_for_event(session: requests.Session, event_url: str) -> List[Dict[str, str]]:
    soup = _get_soup(session, event_url)
    if not soup:
        return []

    comments = []
    comment_divs = soup.find_all('div', class_='message')

    for comment_div in reversed(comment_divs):
        if len(comments) >= 4:
            break

        author_elem = comment_div.find('h5')
        text_elem = comment_div.find('p')

        if author_elem and text_elem:
            author = author_elem.text.strip().split('\n')[0].strip()
            text = text_elem.text.strip()
            comments.append({'author': author, 'text': text})

    return comments

def get_general_comments(session: requests.Session, main_url: str) -> List[Dict[str, str]]:
    soup = _get_soup(session, main_url)
    if not soup:
        return []

    comments = []
    comment_divs = soup.find_all('div', class_='row message')

    for comment_div in reversed(comment_divs):
        if len(comments) >= 4:
            break

        author_elem = comment_div.find('h5')
        text_elem = comment_div.find('p')

        if author_elem and text_elem:
            author = author_elem.text.strip().split('\n')[0].strip()
            text = text_elem.text.strip()
            comments.append({'author': author, 'text': text})

    return comments

def get_kadermanager_events(session: requests.Session, url: str, main_url: str) -> List[Dict[str, Any]]:
    soup = _get_soup(session, url)
    if not soup:
        return [] # Empty list will be handled by caller

    main_soup = _get_soup(session, main_url)

    events = []
    event_containers = soup.find_all('div', class_='event-detailed-container')

    main_enrollments = []
    if main_soup:
        main_enrollments = main_soup.find_all('div', class_='circle-in-enrollments')

    for idx, container in enumerate(event_containers):
        title_elem = container.find('a', class_='event-title-link')
        title = title_elem.text.strip() if title_elem else "Unknown"

        if title_elem and title_elem.has_attr('href'):
            link = title_elem['href']
        else:
             for a in container.find_all('a', href=True):
                href = a['href']
                # Universal fallback: ignore player/edit links AND ensure valid URL
                if "player" not in href and "/edit" not in href and (href.startswith('http') or href.startswith('/')):
                    link = href
                    break

        in_count = "Unknown"
        if idx < len(main_enrollments):
            try:
                in_count = int(main_enrollments[idx].text.strip())
            except (ValueError, AttributeError):
                in_count = "Unknown"

        date_elem = container.find('h4')
        raw_date_str = date_elem.text.strip() if date_elem else "Unknown"

        parsed_date, parsed_time = _parse_date_string(raw_date_str)

        location = "Unknown"
        loc_elem = container.find('div', class_='location')
        if not loc_elem:
            if date_elem:
                possible_loc = date_elem.find_next_sibling('div')
                if possible_loc and 'event-latest-comment' not in possible_loc.get('class', []):
                     location = possible_loc.text.strip()
        else:
            location = loc_elem.text.strip()

        event_type = "Unknown"
        for t in ["Training", "Spiel", "Sonstiges"]:
            if t in title:
                event_type = t
                title = title.replace(t, "").replace(" · ", "").strip()
                break

        events.append({
            'original_date': raw_date_str.replace(" um ", " "),
            'date': parsed_date,
            'time': parsed_time,
            'in_count': in_count,
            'title': title,
            'link': link,
            'location': location,
            'type': event_type,
        })

    return events

def _parse_date_string(date_str: str) -> tuple[str, str]:
    """Parse the date string into ISO date and time."""
    parts = date_str.split(' um ')
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else "Unknown"

    today = datetime.now()
    target_date = today

    if "Heute" in date_part:
        target_date = today
    elif "Morgen" in date_part:
        target_date = today + timedelta(days=1)
    else:
        details = date_part.split()
        clean_date = details[-1] if len(details) > 1 else details[0]
        if clean_date.endswith('.'):
            clean_date = clean_date[:-1]

        if not clean_date[-4:].isdigit():
            clean_date = f"{clean_date}.{today.year}"

        try:
            target_date = datetime.strptime(clean_date, "%d.%m.%Y")
            if target_date.month < today.month - 6:
                 target_date = target_date.replace(year=today.year + 1)
        except ValueError:
            return "Unknown", "Unknown"

    return target_date.strftime("%Y-%m-%d"), time_part
