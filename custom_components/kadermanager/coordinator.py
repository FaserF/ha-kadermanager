import logging
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
import aiohttp
from urllib.parse import urljoin

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import issue_registry as ir, storage

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

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
ISSUE_ID_CONNECTION = "connection_error"

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


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

        self.store = storage.Store(hass, 1, f"{DOMAIN}_{self.teamname}")

        self.last_success: Optional[datetime] = datetime.now()
        self._issue_created = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._logged_in = False
        self._backoff_until: Optional[datetime] = None

        # Increase default update interval if it's too small
        interval = config.get(CONF_UPDATE_INTERVAL, 30)
        if interval < 15:
            _LOGGER.warning(
                "Update interval of %s minutes is too low, using 15 minutes to avoid IP blocks",
                interval,
            )
            interval = 15

        update_interval = timedelta(minutes=interval)

        super().__init__(
            hass,
            _LOGGER,
            name=f"Kadermanager {self.teamname}",
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        if self._backoff_until and datetime.now() < self._backoff_until:
            _LOGGER.debug(
                "Skipping update due to active back-off until %s", self._backoff_until
            )
            return self.data

        try:
            async with asyncio.timeout(60):
                data = await self._async_scrape_data()
                await self.store.async_save(data)
                return data
        except Exception as err:
            # Handle repair logic
            if self.last_success and (datetime.now() - self.last_success) > timedelta(
                hours=24
            ):
                if not self._issue_created:
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        ISSUE_ID_CONNECTION,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="connection_error",
                        learn_more_url="https://github.com/FaserF/ha-kadermanager/issues",
                    )
                    self._issue_created = True

            if isinstance(err, aiohttp.ClientResponseError) and err.status == 429:
                self._backoff_until = datetime.now() + timedelta(hours=1)
                _LOGGER.error(
                    "Received 429 (Too Many Requests). Backing off for 1 hour"
                )

            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _async_scrape_data(self) -> Dict[str, Any]:
        """Asynchronous scraping logic."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=DEFAULT_HEADERS)
            self._logged_in = False

        team_url = f"https://{self.teamname}.kadermanager.de"
        events_url = f"{team_url}/events"
        login_url = f"{team_url}/sessions/new"

        # 1. Login if needed
        if self.username and self.password and not self._logged_in:
            self._logged_in = await self._async_login(login_url)

        # 2. Fetch main events page and home page (for enrollments)
        # We can fetch them in parallel
        events_page, home_page = await asyncio.gather(
            self._async_get_url(events_url), self._async_get_url(team_url)
        )

        if not events_page:
            # Maybe session expired? Try one re-login if we have credentials
            if self.username and self.password:
                _LOGGER.debug("Events page fetch failed, attempting re-login")
                self._logged_in = await self._async_login(login_url)
                events_page = await self._async_get_url(events_url)

            if not events_page:
                raise UpdateFailed("Failed to fetch events page")

        # 3. Parse events
        events = self.parse_events(events_page, home_page, team_url)
        limited_events = events[: self.event_limit]

        # 4. Fetch details for each event (Players & Comments)
        # Optimization: Only fetch details if basic info changed or data missing
        old_events = {
            e["link"]: e for e in (self.data.get("events") or []) if "link" in e
        }

        detail_tasks = []
        for event in limited_events:
            link = event.get("link")

            # Default empty structures
            event["players"] = {
                "accepted_players": [],
                "declined_players": [],
                "no_response_players": [],
            }
            event["comments"] = []

            # Check if we can reuse cached details
            if link in old_events:
                old_e = old_events[link]
                if old_e.get("in_count") == event.get("in_count") and old_e.get(
                    "original_date"
                ) == event.get("original_date"):
                    _LOGGER.debug(
                        "Reusing cached details for event: %s", event.get("title")
                    )
                    event["players"] = old_e.get("players", event["players"])
                    event["comments"] = old_e.get("comments", event["comments"])
                    continue

            if self.fetch_player_info or self.fetch_comments:
                if link and link != events_url:
                    if link.startswith("/"):
                        link = f"{team_url}{link}"
                    detail_tasks.append(self._async_fetch_event_details(event, link))

        if detail_tasks:
            _LOGGER.debug("Fetching details for %s event(s)", len(detail_tasks))
            # Use a semaphore to limit concurrency and avoid bot detection,
            # while still being faster than purely sequential fetching.
            semaphore = asyncio.Semaphore(2)

            async def sem_task(task):
                async with semaphore:
                    await task
                    await asyncio.sleep(0.2)  # Tiny jitter between requests

            await asyncio.gather(*(sem_task(task) for task in detail_tasks))

        data = {"events": limited_events}

        if self.fetch_comments and home_page:
            data["general_comments"] = self.parse_general_comments(home_page)

        # Update success state
        self.last_success = datetime.now()
        if self._issue_created:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID_CONNECTION)
            self._issue_created = False

        return data

    async def async_close(self):
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def async_load_cache(self):
        """Load cached data from storage."""
        cache = await self.store.async_load()
        if cache:
            _LOGGER.debug("Loaded cached data for %s", self.teamname)
            self.data = cache
            # Try to restore last success time if possible (not strictly needed but good)
            # For now we just use the data.

    async def _async_login(self, login_url: str) -> bool:
        """Perform login and update session cookies."""
        try:
            _LOGGER.debug("Accessing login page for CSRF token")
            assert self._session is not None
            async with self._session.get(login_url, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            token_input = soup.find("input", {"name": "authenticity_token"})
            if not token_input:
                _LOGGER.error("Could not find authenticity_token on login page")
                return False
            token = token_input.get("value") if token_input else ""

            payload = {
                "authenticity_token": token,
                "login_name": self.username,
                "password": self.password,
            }

            form = soup.find("form", id="login_form") or soup.find(
                "form", action=lambda x: x and "sessions" in x
            )
            post_url = login_url
            if form and form.get("action"):
                action = str(form.get("action"))
                post_url = urljoin(login_url, action)

            _LOGGER.debug("Submitting login form")
            assert self._session is not None
            async with self._session.post(
                post_url, data=payload, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if "Invalid login" in text or "Anmeldung fehlgeschlagen" in text:
                        _LOGGER.error("Login failed: Invalid credentials")
                        return False
                    _LOGGER.debug("Login successful")
                    return True
                return False
        except Exception as e:
            _LOGGER.error("Exception during login: %s", e)
            return False

    async def _async_get_url(self, url: str) -> Optional[str]:
        """Fetch URL content."""
        try:
            assert self._session is not None
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 429:
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history, status=429
                    )
                resp.raise_for_status()
                return await resp.text()
        except Exception as e:
            _LOGGER.error("Failed to fetch %s: %s", url, e)
            return None

    async def _async_fetch_event_details(self, event: Dict[str, Any], url: str):
        """Fetch and parse players/comments for a specific event."""
        html = await self._async_get_url(url)
        if not html:
            return

        soup = BeautifulSoup(html, "html.parser")

        if self.fetch_player_info:
            event["players"] = self.parse_event_players(soup)
            # Optimization: If we have the exact player list, update the in_count if it was unknown
            accepted_count = len(event["players"].get("accepted_players", []))
            if accepted_count > 0:
                event["in_count"] = accepted_count

        if self.fetch_comments:
            event["comments"] = self.parse_event_comments(soup)

    def parse_events(
        self, events_html: str, home_html: Optional[str], team_url: str
    ) -> List[Dict[str, Any]]:
        """Parse the events list."""
        soup = BeautifulSoup(events_html, "html.parser")
        event_containers = soup.find_all("div", class_="event-detailed-container")

        # Try to match enrollments from home page by event link/title if possible
        enrollment_map = {}
        if home_html:
            home_soup = BeautifulSoup(home_html, "html.parser")
            # The home page usually has "circle-in-enrollments" inside a container that might have a link
            enrollment_divs = home_soup.find_all("div", class_="circle-in-enrollments")
            for div in enrollment_divs:
                try:
                    count = int(div.text.strip())
                    # Look for the closest link to this enrollment circle
                    parent_link = div.find_parent("a", href=True)
                    if parent_link:
                        # Normalize link to relative path
                        raw_href = str(parent_link["href"])
                        link_path = (
                            "/" + "/".join(raw_href.split("/")[3:])
                            if "://" in raw_href
                            else raw_href
                        ).split("?")[0]
                        enrollment_map[link_path] = count
                except (ValueError, AttributeError):
                    continue

        events = []
        for idx, container in enumerate(event_containers):
            title_elem = container.find("a", class_="event-title-link")
            title = title_elem.text.strip() if title_elem else "Unknown"

            link = ""
            if title_elem and title_elem.has_attr("href"):
                link = str(title_elem["href"])
            else:
                for a in container.find_all("a", href=True):
                    href = a["href"]
                    if "player" not in href and "/edit" not in href:
                        link = str(href)
                        break

            if link.startswith("/"):
                link = f"{team_url}{link}"

            in_count: int | str = "Unknown"
            # Try to match by link first (most robust)
            link_path = "/" + "/".join(link.split("/")[3:]) if "://" in link else link
            if link_path in enrollment_map:
                in_count = enrollment_map[link_path]
            # Fallback to index only if we have exactly the same number of items and no links found
            elif idx < len(enrollment_map) and not enrollment_map:
                # This is the old behavior as absolute fallback
                in_count = list(enrollment_map.values())[idx]

            date_elem = container.find("h4")
            raw_date_str = date_elem.text.strip() if date_elem else "Unknown"
            parsed_date, parsed_time = self.parse_date_string(raw_date_str)

            location = "Unknown"
            loc_elem = container.find("div", class_="location")
            if not loc_elem and date_elem:
                possible_loc = date_elem.find_next_sibling("div")
                if possible_loc and "event-latest-comment" not in (
                    possible_loc.get("class") or []
                ):
                    location = possible_loc.text.strip()
            elif loc_elem:
                location = loc_elem.text.strip()

            event_type = "Unknown"
            for t in ["Training", "Spiel", "Sonstiges"]:
                if t in title:
                    event_type = t
                    title = title.replace(t, "").replace(" · ", "").strip()
                    break

            events.append(
                {
                    "original_date": raw_date_str.replace(" um ", " "),
                    "date": parsed_date,
                    "time": parsed_time,
                    "in_count": in_count,
                    "title": title,
                    "link": link or team_url,
                    "location": location,
                    "type": event_type,
                }
            )
        return events

    def parse_event_players(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Parse player list from event page."""
        player_types: Dict[str, List[str]] = {
            "accepted_players": [],
            "declined_players": [],
            "no_response_players": [],
        }
        drop_zones = soup.find_all("div", class_="drop-zone")
        for zone in drop_zones:
            zone_id = zone.get("id")
            players = [
                label.text.strip()
                for label in zone.find_all("span", class_="player_label")
            ]
            if zone_id == "zone_1":
                player_types["accepted_players"] = players
            elif zone_id == "zone_2":
                player_types["declined_players"] = players
            elif zone_id == "zone_3":
                player_types["no_response_players"] = players
        return player_types

    def parse_event_comments(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Parse comments from event page."""
        comments: List[Dict[str, str]] = []
        comment_divs = soup.find_all("div", class_="message")
        for comment_div in reversed(comment_divs):
            if len(comments) >= 5:
                break
            author_elem = comment_div.find("h5")
            text_elem = comment_div.find("p")
            if author_elem and text_elem:
                author = author_elem.text.strip().split("\n")[0].strip()
                comments.append({"author": author, "text": text_elem.text.strip()})
        return comments

    def parse_general_comments(self, html: str) -> List[Dict[str, str]]:
        """Parse general team comments."""
        soup = BeautifulSoup(html, "html.parser")
        comments: List[Dict[str, str]] = []
        comment_divs = soup.find_all("div", class_="row message")
        for comment_div in reversed(comment_divs):
            if len(comments) >= 5:
                break
            author_elem = comment_div.find("h5")
            text_elem = comment_div.find("p")
            if author_elem and text_elem:
                author = author_elem.text.strip().split("\n")[0].strip()
                comments.append({"author": author, "text": text_elem.text.strip()})
        return comments

    def parse_date_string(self, date_str: str) -> tuple[str, str]:
        """Convert German relative/absolute date string to ISO."""
        parts = date_str.split(" um ")
        date_part = parts[0]
        time_part = parts[1] if len(parts) > 1 else "Unknown"

        today = datetime.now()
        target_date = today

        if "Heute" in date_part:
            target_date = today
        elif "Morgen" in date_part:
            target_date = today + timedelta(days=1)
        else:
            # Handle formats like "10.04.", "10. April", "Fr 10.04."
            details = date_part.replace(",", "").split()
            day_str = details[-1].strip() if details else ""

            # Remove trailing dots
            if day_str.endswith("."):
                day_str = day_str[:-1]

            # Try to map German month names
            month_map = {
                "Jan": "01",
                "Feb": "02",
                "Mär": "03",
                "Apr": "04",
                "Mai": "05",
                "Jun": "06",
                "Jul": "07",
                "Aug": "08",
                "Sep": "09",
                "Okt": "10",
                "Nov": "11",
                "Dez": "12",
                "Januar": "01",
                "Februar": "02",
                "März": "03",
                "April": "04",
                "Juni": "06",
                "Juli": "07",
                "August": "08",
                "September": "09",
                "Oktober": "10",
                "November": "11",
                "Dezember": "12",
            }

            try:
                if "." in day_str:
                    # Format: 10.04.
                    d_parts = day_str.split(".")
                    if len(d_parts) >= 2:
                        day = d_parts[0]
                        month = d_parts[1]
                        year = d_parts[2] if len(d_parts) > 2 else str(today.year)
                        target_date = datetime.strptime(
                            f"{day}.{month}.{year}", "%d.%m.%Y"
                        )
                else:
                    # Maybe format: 10 April
                    month_name = details[-1]
                    day_num = details[-2] if len(details) > 1 else ""
                    if month_name in month_map and day_num.isdigit():
                        target_date = datetime.strptime(
                            f"{day_num}.{month_map[month_name]}.{today.year}",
                            "%d.%m.%Y",
                        )
                    else:
                        raise ValueError("Unknown format")

                # Season rollover heuristic: if date is > 6 months in past, it's likely next year
                if target_date.month < today.month - 6:
                    target_date = target_date.replace(year=today.year + 1)
            except (ValueError, IndexError):
                _LOGGER.debug("Could not parse date string: %s", date_str)
                return "Unknown", "Unknown"

        return target_date.strftime("%Y-%m-%d"), time_part


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> None:
    """Validate the user input allows us to connect (Shared validation)."""
    teamname = data[CONF_TEAM_NAME]
    username = data.get(CONF_USERNAME)
    password = data.get(CONF_PASSWORD)

    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
        main_url = f"https://{teamname}.kadermanager.de"
        try:
            async with session.get(main_url, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
        except Exception as e:
            _LOGGER.error("Validation failed connecting to %s: %s", main_url, e)
            raise CannotConnect from e

        if username and password:
            login_url = f"{main_url}/sessions/new"
            # We reuse the logic but in a simplified way for validation
            # Since we don't have a coordinator yet.
            try:
                async with session.get(login_url, timeout=REQUEST_TIMEOUT) as resp:
                    resp.raise_for_status()
                    html = await resp.text()

                soup = BeautifulSoup(html, "html.parser")
                token = soup.find("input", {"name": "authenticity_token"})
                token_val = token.get("value") if token else ""

                payload = {
                    "authenticity_token": token_val,
                    "login_name": username,
                    "password": password,
                }

                form = soup.find("form", id="login_form") or soup.find(
                    "form", action=lambda x: x and "sessions" in x
                )
                post_url = (
                    urljoin(login_url, str(form.get("action")))
                    if form and form.get("action")
                    else login_url
                )

                async with session.post(
                    post_url, data=payload, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        if (
                            "Invalid login" in text
                            or "Anmeldung fehlgeschlagen" in text
                        ):
                            raise InvalidAuth
                    else:
                        raise CannotConnect
            except (InvalidAuth, CannotConnect):
                raise
            except Exception as e:
                _LOGGER.error("Validation error: %s", e)
                raise CannotConnect from e
