import logging
import requests
import async_timeout
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    CONF_TEAM_NAME,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_EVENT_LIMIT,
    CONF_FETCH_PLAYER_INFO,
    CONF_FETCH_COMMENTS,
)

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
REQUEST_TIMEOUT = 15
ISSUE_ID_CONNECTION = "connection_error"

class KadermanagerDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Kadermanager data."""

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]):
        """Initialize."""
        self.teamname = config[CONF_TEAM_NAME]
        self.username = config.get(CONF_USERNAME)
        self.password = config.get(CONF_PASSWORD)
        self.event_limit = config.get(CONF_EVENT_LIMIT, 5)
        self.fetch_player_info = config.get(CONF_FETCH_PLAYER_INFO, False)
        self.fetch_comments = config.get(CONF_FETCH_COMMENTS, False)

        self._last_success: Optional[datetime] = datetime.now()
        self._issue_created = False

        update_interval = timedelta(minutes=config.get(CONF_UPDATE_INTERVAL, 30))

        super().__init__(
            hass,
            _LOGGER,
            name=f"Kadermanager {self.teamname}",
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            async with async_timeout.timeout(45):
                return await self.hass.async_add_executor_job(self._scrape_data)
        except Exception as err:
            # Handle repair logic
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

            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def _scrape_data(self) -> Dict[str, Any]:
        """Synchronous scraping job."""
        session = requests.Session()
        session.headers.update({'User-Agent': USER_AGENT})

        url = f"https://{self.teamname}.kadermanager.de/events"
        main_url = f"https://{self.teamname}.kadermanager.de"
        login_url = f"https://{self.teamname}.kadermanager.de/sessions/new"

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
                    # Resolve relative URLs if any (though logic usually returns absolute)
                    if event_url.startswith("/"):
                        event_url = f"https://{self.teamname}.kadermanager.de{event_url}"

                    players = get_players_for_event(session, event_url)
                    event['players'] = players

                    if self.fetch_comments:
                        comments = get_comments_for_event(session, event_url)
                        event['comments'] = comments

        data = {'events': limited_events}

        if self.fetch_comments:
             general_comments = get_general_comments(session, main_url)
             data['general_comments'] = general_comments

        # If successful update
        self._last_success = datetime.now()
        if self._issue_created:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID_CONNECTION)
            self._issue_created = False

        return data

# --- Scraper Helper Functions (moved from sensor.py) ---

def _login(session: requests.Session, login_url: str, username: str, password: str):
    """Perform login."""
    try:
        _LOGGER.debug(f"Accessing login page: {login_url}")
        r_get = session.get(login_url, timeout=REQUEST_TIMEOUT)
        r_get.raise_for_status()

        soup = BeautifulSoup(r_get.text, 'html.parser')

        token_input = soup.find('input', {'name': 'authenticity_token'})
        if not token_input:
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

        r_post = session.post(post_url, data=payload, timeout=REQUEST_TIMEOUT)

        if r_post.status_code == 200:
            if "Invalid login" in r_post.text or "Anmeldung fehlgeschlagen" in r_post.text:
                _LOGGER.error("Login failed. Continuing as guest.")
            else:
                _LOGGER.debug("Login successful.")

    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")

def _get_soup(session: requests.Session, url: str) -> Optional[BeautifulSoup]:
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
        return []

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
                if "player" not in href and "/edit" not in href and (href.startswith('http') or href.startswith('/')):
                    link = href
                    break
             else:
                 link = url

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

        # If year missing (e.g. "2.2."), append current year
        if not clean_date[-4:].isdigit():
            clean_date = f"{clean_date}.{today.year}"

        try:
            target_date = datetime.strptime(clean_date, "%d.%m.%Y")
            # Handle past events being next year (e.g. parsing a date in January when we are in December)
            # Actually logic was: if target date month < current month - 6, assume next year.
            if target_date.month < today.month - 6:
                 target_date = target_date.replace(year=today.year + 1)
            # Logic for year wrap around if date is in past but logic thinks it is this year?
            # Basic scraper usually shows future events.
        except ValueError:
            return "Unknown", "Unknown"

    return target_date.strftime("%Y-%m-%d"), time_part
