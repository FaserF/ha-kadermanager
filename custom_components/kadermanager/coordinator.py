import logging
import asyncio
import socket
import random

from datetime import datetime, timedelta
from homeassistant.util import dt as dt_util
from typing import Any, Dict, List, Optional
import re
from bs4 import BeautifulSoup
import aiohttp
from urllib.parse import urljoin

from homeassistant import config_entries
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
    CONF_FORCE_UPDATE,
    CONF_DYNAMIC_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) Gecko/20100101 Firefox/145.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:145.0) Gecko/20100101 Firefox/145.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0",
]

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

ISSUE_ID_CONNECTION = "connection_error"


def get_random_headers(teamname: str) -> Dict[str, str]:
    """Generate random headers to mimic a real browser."""
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": f"https://{teamname.lower()}.kadermanager.de/",
    }

    # Add Sec-CH-UA headers for Chrome-based browsers
    if "Chrome" in ua:
        headers["Sec-CH-UA"] = (
            '"Google Chrome";v="148", "Chromium";v="148", "Not=A?Brand";v="99"'
        )
        headers["Sec-CH-UA-Mobile"] = "?0"
        headers["Sec-CH-UA-Platform"] = '"Windows"' if "Windows" in ua else '"macOS"'

    return headers


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


class KadermanagerDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Kadermanager data."""

    config_entry: config_entries.ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: config_entries.ConfigEntry):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=max(60, entry.options.get(CONF_UPDATE_INTERVAL, 60))
            ),
        )
        self.hass = hass
        config = {**entry.data, **entry.options}
        self.config_entry = entry
        self.teamname = config[CONF_TEAM_NAME]
        self.username = config.get(CONF_USERNAME)
        self.password = config.get(CONF_PASSWORD)
        self.event_limit = config.get(CONF_EVENT_LIMIT, 5)
        self.fetch_player_info = config.get(CONF_FETCH_PLAYER_INFO, False)
        self.fetch_comments = config.get(CONF_FETCH_COMMENTS, False)
        self._force_update = entry.options.get(CONF_FORCE_UPDATE, False)

        self.store: storage.Store = storage.Store(hass, 1, f"{DOMAIN}_{self.teamname}")

        self.last_success: Optional[datetime] = None
        self._issue_created = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._logged_in = False
        self._backoff_until: Optional[datetime] = None
        self._consecutive_failures = 0
        self._headers = get_random_headers(self.teamname)

        # Increase default update interval if it's too small
        interval = config.get(CONF_UPDATE_INTERVAL, 60)
        if interval < 60:
            _LOGGER.warning(
                "Update interval of %s minutes is too low, using 60 minutes to avoid IP blocks (softbans)",
                interval,
            )
            interval = 60

        update_interval = timedelta(minutes=interval)

        super().__init__(
            hass,
            _LOGGER,
            name=f"Kadermanager {self.teamname}",
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        # Check if we should skip this update due to active back-off
        # Bypass if it's a forced update from the UI
        if (
            not self._force_update
            and self._backoff_until
            and dt_util.now() < self._backoff_until
        ):
            _LOGGER.debug(
                "Skipping update due to active back-off until %s", self._backoff_until
            )
            return self.data

        # Restart-resistance: Skip update if the last successful scrape was too recent
        # (e.g. after a HA restart), unless it's a forced update.
        if not self._force_update and self.last_success is not None:
            last_success: datetime = self.last_success
            time_since_last = dt_util.now() - last_success
            update_interval: timedelta = self.update_interval or timedelta(minutes=60)
            # We use a 15-minute buffer to ensure we don't skip when it's actually time
            if time_since_last < (update_interval - timedelta(minutes=15)):
                _LOGGER.info(
                    "Skipping scrape for %s: Last successful update was only %s minutes ago. Respecting update interval of %s minutes.",
                    self.teamname,
                    int(time_since_last.total_seconds() / 60),
                    int(update_interval.total_seconds() / 60),
                )
                return self.data

        try:
            # Get or create a domain-wide lock to prevent multiple Kadermanager entries
            # from scraping at the exact same time (e.g. after a HA reboot).
            domain_data = self.hass.data.setdefault(DOMAIN, {})
            scrape_lock = domain_data.setdefault("scrape_lock", asyncio.Lock())

            async with scrape_lock:
                # Add a significant random delay to avoid fixed-interval detection
                if not self._force_update:
                    _LOGGER.debug("Waiting for random jitter delay (5-30s)")
                    await asyncio.sleep(random.uniform(5.0, 30.0))
                else:
                    _LOGGER.info("Force update triggered, bypassing jitter delay")
                    self._force_update = False  # Reset for next regular update

                async with asyncio.timeout(60):
                    data = await self._async_scrape_data()
                    self.last_success = dt_util.now()
                    # Persist the success time to avoid aggressive scraping after restarts
                    data["last_success"] = self.last_success.isoformat()
                    await self.store.async_save(data)
                    self._consecutive_failures = 0
                    self._update_dynamic_interval(data)
                    return data
        except Exception as err:
            # Handle repair logic
            if self.last_success and (dt_util.now() - self.last_success) > timedelta(
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

            status = getattr(err, "status", None)
            if status in [403, 429]:
                self._consecutive_failures += 1
                backoff_hours = min(24, self._consecutive_failures * 2)
                self._backoff_until = dt_util.now() + timedelta(hours=backoff_hours)
                _LOGGER.error(
                    "Received %s (Blocked). Backing off for %s hours",
                    getattr(err, "status", "unknown"),
                    backoff_hours,
                )
            elif (
                isinstance(err, (aiohttp.ClientConnectorError, CannotConnect))
                or "ClientConnectorError" in str(type(err))
                or (
                    isinstance(err, UpdateFailed)
                    and (
                        "Connect call failed" in str(err)
                        or "Failed to fetch events page" in str(err)
                    )
                )
            ):
                self._consecutive_failures += 1
                backoff_minutes = min(1440, self._consecutive_failures * 60)
                self._backoff_until = dt_util.now() + timedelta(minutes=backoff_minutes)
                _LOGGER.error(
                    "Connection dropped or failed. Consecutive failures: %s. Backing off for %s minutes",
                    self._consecutive_failures,
                    backoff_minutes,
                )
            else:
                # Other errors
                self._consecutive_failures += 1

            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def _update_dynamic_interval(self, data: Dict[str, Any]) -> None:
        """Update the update interval dynamically based on upcoming and recent events."""
        if not self.config_entry.options.get(CONF_DYNAMIC_INTERVAL):
            # Fallback to configured fixed interval
            self.update_interval = timedelta(
                minutes=max(60, self.config_entry.options.get(CONF_UPDATE_INTERVAL, 60))
            )
            return

        events = data.get("events", [])
        now = dt_util.now()

        # Default to 12 hours
        min_interval = timedelta(hours=12)
        interval_reason = "No active or upcoming events"

        for event in events:
            try:
                event_date = event.get("date")
                event_time = event.get("time")

                if not event_date:
                    continue

                if not event_time or event_time == "Unknown":
                    event_time = "00:00"

                edt = dt_util.parse_datetime(f"{event_date} {event_time}")
                if edt:
                    if edt.tzinfo is None:
                        edt = dt_util.as_local(edt)

                    time_diff = edt - now

                    # 1. ACTIVE PHASE: During or shortly after (up to 3 hours after start)
                    # Use 30 minutes to catch late comments or attendance changes during the event
                    if timedelta(hours=-3) <= time_diff <= timedelta(0):
                        if min_interval > timedelta(minutes=30):
                            min_interval = timedelta(minutes=30)
                            interval_reason = f"Event '{event.get('title')}' is active (started {edt})"

                    # 2. RECAP PHASE: 3 to 6 hours after start
                    # Use 2 hours for post-event summary/comments
                    elif timedelta(hours=-6) < time_diff < timedelta(hours=-3):
                        if min_interval > timedelta(hours=2):
                            min_interval = timedelta(hours=2)
                            interval_reason = f"Event '{event.get('title')}' finished recently (started {edt})"

                    # 3. PROXIMITY PHASE: Within 24 hours before start
                    # Use 60 minutes
                    elif timedelta(0) < time_diff <= timedelta(hours=24):
                        if min_interval > timedelta(hours=1):
                            min_interval = timedelta(hours=1)
                            interval_reason = f"Event '{event.get('title')}' is upcoming (starts {edt})"

            except (ValueError, TypeError):
                continue

        self.update_interval = min_interval
        _LOGGER.info(
            "Dynamic interval set to %s. Reason: %s",
            self.update_interval,
            interval_reason,
        )

    async def _async_scrape_data(self) -> Dict[str, Any]:
        """Asynchronous scraping logic."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            self._headers = get_random_headers(self.teamname)
            self._session = aiohttp.ClientSession(
                headers=self._headers, connector=connector
            )
            self._logged_in = False

        teamname_lower = self.teamname.lower()
        team_url = f"https://{teamname_lower}.kadermanager.de"
        events_url = f"{team_url}/events"
        login_url = f"{team_url}/sessions/new"
        ical_url = f"{team_url}/calendar/ical"
        events_widget_url = f"{team_url}/calendar/widget_iframe_events"
        messages_widget_url = f"{team_url}/messages/widget_iframe_messages"

        # 1. Login if needed
        if self.username and self.password and not self._logged_in:
            self._logged_in = await self._async_login(login_url)
            await asyncio.sleep(random.uniform(3.0, 5.0))

        # 2. Try fetching data via iCal and Widgets (Safer path)
        ical_events = await self._async_get_ical_data(ical_url)
        await asyncio.sleep(random.uniform(2.0, 4.0))
        widget_html = await self._async_get_url(events_widget_url)
        await asyncio.sleep(random.uniform(2.0, 4.0))
        messages_html = await self._async_get_url(messages_widget_url)

        if ical_events:
            _LOGGER.debug("Using iCal and Widget data for %s events", len(ical_events))
            enrollment_counts = (
                self._parse_widget_events(widget_html) if widget_html else {}
            )

            # Combine iCal events with enrollment counts
            events = []
            now = dt_util.now()
            today_str = now.strftime("%Y-%m-%d")

            for e in ical_events:
                if not e.get("date"):
                    continue

                # Create a key for matching: Title_DD.MM.
                d_parts = e["date"].split("-")
                date_key = f"{d_parts[2]}.{d_parts[1]}."
                match_key = f"{e['title']}_{date_key}"

                e["in_count"] = enrollment_counts.get(match_key)

                # Check if event is in the past
                # If time is unknown, we assume it's an all-day event and keep it for the whole day
                event_time = e.get("time", "23:59")
                if event_time == "Unknown":
                    event_time = "23:59"

                try:
                    # Construct aware datetime for comparison
                    if event_time != "23:59":
                        event_dt = dt_util.parse_datetime(f"{e['date']} {event_time}")
                    else:
                        event_dt = dt_util.parse_datetime(f"{e['date']} 23:59:59")

                    if event_dt and event_dt + timedelta(hours=1) < now:
                        _LOGGER.debug(
                            "Skipping past event: %s on %s", e["title"], e["date"]
                        )
                        continue
                except (ValueError, TypeError):
                    if e["date"] < today_str:
                        continue

                events.append(e)

            # Sort events chronologically
            events.sort(key=lambda x: (x["date"], x.get("time", "00:00")))

            # Limited events
            limited_events = events[: self.event_limit]

            # Fetch details if needed
            detail_tasks = []
            for event in limited_events:
                link = event.get("link")
                event["players"] = {
                    "accepted_players": [],
                    "declined_players": [],
                    "no_response_players": [],
                }
                event["comments"] = []

                if (self.fetch_player_info or self.fetch_comments) and link:
                    # Reuse cache logic
                    old_events = {
                        ev["link"]: ev
                        for ev in ((self.data or {}).get("events") or [])
                        if "link" in ev
                    }
                    if link in old_events:
                        old_e = old_events[link]
                        if old_e.get("in_count") == event.get("in_count"):
                            event["players"] = old_e.get("players", event["players"])
                            event["comments"] = old_e.get("comments", event["comments"])
                            continue

                    detail_tasks.append(self._async_fetch_event_details(event, link))

            if detail_tasks:
                semaphore = asyncio.Semaphore(1)

                async def sem_task(task):
                    async with semaphore:
                        await task
                        await asyncio.sleep(random.uniform(3.0, 8.0))

                await asyncio.gather(*(sem_task(task) for task in detail_tasks))

            data = {"events": limited_events}
            if self.fetch_comments and messages_html:
                data["general_comments"] = self.parse_general_comments(messages_html)

            self.last_success = dt_util.now()
            return data

        # 3. Fallback to full scraping if iCal failed
        _LOGGER.debug("iCal fetch failed or empty, falling back to full scraping")
        events_page = await self._async_get_url(events_url)
        await asyncio.sleep(random.uniform(2.5, 6.0))
        home_page = await self._async_get_url(team_url)

        if not events_page:
            # Maybe session expired? Try one re-login if we have credentials
            if self.username and self.password:
                _LOGGER.debug("Events page fetch failed, attempting re-login")
                await asyncio.sleep(random.uniform(2.0, 4.0))
                self._logged_in = await self._async_login(login_url)
                await asyncio.sleep(random.uniform(1.5, 3.0))
                events_page = await self._async_get_url(events_url)

            if not events_page:
                raise UpdateFailed(
                    "Failed to fetch events page (maybe IP blocked or session expired)"
                )

        # 3. Parse and filter events
        all_parsed_events = self.parse_events(events_page, home_page, team_url)

        events = []
        now = dt_util.now()
        today_str = now.strftime("%Y-%m-%d")

        for e in all_parsed_events:
            if not e.get("date"):
                continue

            # Check if event is in the past
            event_time = e.get("time", "23:59")
            if not event_time or event_time == "Unknown":
                event_time = "23:59"

            try:
                # Construct aware datetime for comparison
                if event_time != "23:59":
                    event_dt = dt_util.parse_datetime(f"{e['date']} {event_time}")
                else:
                    event_dt = dt_util.parse_datetime(f"{e['date']} 23:59:59")

                if event_dt and event_dt + timedelta(hours=1) < now:
                    _LOGGER.debug(
                        "Skipping past event: %s on %s", e["title"], e["date"]
                    )
                    continue
            except (ValueError, TypeError):
                if e["date"] < today_str:
                    continue

            events.append(e)

        # Sort events chronologically
        events.sort(key=lambda x: (x["date"], x.get("time", "00:00")))
        limited_events = events[: self.event_limit]

        # 4. Fetch details for each event (Players & Comments)
        # Optimization: Only fetch details if basic info changed or data missing
        old_events = {
            e["link"]: e for e in ((self.data or {}).get("events") or []) if "link" in e
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
            # Use a semaphore of 1 (sequential) to completely avoid parallel requests
            # and use random delays to simulate human behavior.
            semaphore = asyncio.Semaphore(1)

            async def sem_task(task):
                async with semaphore:
                    await task
                    await asyncio.sleep(
                        random.uniform(3.0, 8.0)
                    )  # Significant random jitter between requests

            await asyncio.gather(*(sem_task(task) for task in detail_tasks))

        data = {"events": limited_events}

        if self.fetch_comments and home_page:
            data["general_comments"] = self.parse_general_comments(home_page)

        # Update success state
        self.last_success = dt_util.now()
        if self._issue_created:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID_CONNECTION)
            self._issue_created = False

        return data

    async def _async_get_ical_data(self, url: str) -> List[Dict[str, Any]]:
        """Fetch and parse iCal data."""
        content = await self._async_get_url(url)
        if not content:
            return []

        events = []
        current_event: Dict[str, Any] = {}
        # Unfold lines (iCal lines starting with space are continuations)
        lines = content.replace("\r\n ", "").replace("\n ", "").splitlines()

        for line in lines:
            if line == "BEGIN:VEVENT":
                current_event = {}
            elif line == "END:VEVENT":
                if "SUMMARY" in current_event and "DTSTART" in current_event:
                    events.append(current_event)
            elif ":" in line:
                key_part, value = line.split(":", 1)
                key = key_part.split(";")[0]
                # Unescape some common chars
                value = (
                    value.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n")
                )
                current_event[key] = value

        parsed_events = []
        for e in events:
            # Parse DTSTART (e.g. 20260623T193000Z or 20260623)
            dt_str = e.get("DTSTART", "")
            try:
                if "T" in dt_str:
                    dt = datetime.strptime(dt_str[:15], "%Y%m%dT%H%M%S")
                    if dt_str.endswith("Z"):
                        dt = dt.replace(tzinfo=dt_util.UTC)
                        dt = dt_util.as_local(dt)
                else:
                    dt = datetime.strptime(dt_str[:8], "%Y%m%d")

                parsed_events.append(
                    {
                        "title": e.get("SUMMARY", "Unknown"),
                        "link": e.get("URL", ""),
                        "location": e.get("LOCATION", "Unknown"),
                        "type": e.get("CATEGORIES", "Unknown"),
                        "date": dt.strftime("%Y-%m-%d"),
                        "time": dt.strftime("%H:%M") if "T" in dt_str else "Unknown",
                        "original_date": dt.strftime("%d.%m.%Y %H:%M"),
                    }
                )
            except Exception:
                continue

        return parsed_events

    def _parse_widget_events(self, html: str) -> Dict[str, int]:
        """Parse enrollment counts from the events widget."""
        soup = BeautifulSoup(html, "html.parser")
        counts = {}
        event_divs = soup.find_all("div", class_="event")
        for div in event_divs:
            title_elem = div.find("div", class_="what")
            date_elem = div.find("span", class_="date")
            count_elem = div.find("span", class_="enrolled_in")

            if title_elem and date_elem and count_elem:
                title = title_elem.text.strip()
                # Extract DD.MM from date_elem (e.g. "Di 23.06.")
                date_match = re.search(r"(\d{2}\.\d{2}\.)", date_elem.text)
                if date_match:
                    date_key = date_match.group(1)
                    # Extract count from "(Teilnehmer: 5)"
                    count_match = re.search(r"(\d+)", count_elem.text)
                    if count_match:
                        counts[f"{title}_{date_key}"] = int(count_match.group(1))
        return counts

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
            # Restore last success time to ensure restart-resistance
            if "last_success" in cache:
                try:
                    self.last_success = dt_util.parse_datetime(cache["last_success"])
                except (ValueError, TypeError):
                    self.last_success = None

    async def _async_login(self, login_url: str) -> bool:
        """Perform login and update session cookies."""
        try:
            _LOGGER.debug("Accessing login page for CSRF token")
            assert self._session is not None
            async with self._session.get(login_url, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            token = ""
            token_input = soup.find("input", {"name": "authenticity_token"})
            if token_input:
                t_val = token_input.get("value")
                token = str(t_val[0] if isinstance(t_val, list) else t_val or "")
            else:
                # Fallback to meta tag if input not found
                token_meta = soup.find("meta", {"name": "csrf-token"})
                if token_meta:
                    token_val = token_meta.get("content")
                    token = str(
                        token_val[0] if isinstance(token_val, list) else token_val or ""
                    )

            if not token:
                _LOGGER.error(
                    "Could not find authenticity_token or csrf-token on login page"
                )
                return False

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
            await asyncio.sleep(random.uniform(1.5, 3.5))
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
            # Use stored headers but update Referer if needed (though it's usually static enough)
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if "sessions/new" in str(resp.url) and "sessions/new" not in url:
                    _LOGGER.debug(
                        "Redirected to login page, session likely expired or unauthorized"
                    )
                    self._logged_in = False
                    return None

                if resp.status == 429:
                    _LOGGER.error("Rate limit hit (429) for %s", url)
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history, status=429
                    )
                if resp.status == 403:
                    _LOGGER.error(
                        "Access forbidden (403) for %s - possibly bot detection or IP ban",
                        url,
                    )

                resp.raise_for_status()
                return await resp.text()
        except aiohttp.ClientResponseError as e:
            _LOGGER.error(
                "HTTP error fetching %s: %s (Status: %s)", url, e.message, e.status
            )
            return None
        except aiohttp.ClientConnectorError as e:
            _LOGGER.error(
                "Connection error fetching %s: %s - possibly softbanned", url, e
            )
            raise CannotConnect(f"Connection failed: {e}") from e
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
            for idx, div in enumerate(enrollment_divs):
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
                    else:
                        # Fallback: store by index string
                        enrollment_map[f"idx_{idx}"] = count
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

            in_count: int | None = None
            # Try to match by link first (most robust)
            link_path = "/" + "/".join(link.split("/")[3:]) if "://" in link else link
            if link_path in enrollment_map:
                in_count = enrollment_map[link_path]
            # Fallback to index if link matching fails
            elif f"idx_{idx}" in enrollment_map:
                in_count = enrollment_map[f"idx_{idx}"]

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

    def parse_date_string(self, date_str: str) -> tuple[Optional[str], Optional[str]]:
        """Convert German relative/absolute date string to ISO."""
        # Handle "07.04.2026 17:30" format directly if present
        date_time_match = re.search(
            r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}:\d{2})", date_str
        )
        if date_time_match:
            d, m, y, t = date_time_match.groups()
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}", t

        parts = date_str.split(" um ")
        date_part = parts[0]
        time_part = parts[1] if len(parts) > 1 else "Unknown"

        today = dt_util.now()
        target_date = today

        if "Heute" in date_part:
            target_date = today
        elif "Morgen" in date_part:
            target_date = today + timedelta(days=1)
        else:
            # Handle formats like "10.04.", "10. April", "Fr 10.04.", "07.04.2026"
            details = date_part.replace(",", "").split()
            if not details:
                return None, None

            # Search for something that looks like a date (contains dots)
            day_str = ""
            for detail in details:
                if "." in detail:
                    day_str = detail
                    break

            if not day_str:
                day_str = details[-1]  # Fallback to last element

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
                    # Format: 10.04. or 10.04.2026
                    d_parts = day_str.split(".")
                    if len(d_parts) >= 2:
                        day = d_parts[0].zfill(2)
                        month = d_parts[1].zfill(2)
                        year = (
                            d_parts[2]
                            if len(d_parts) > 2 and len(d_parts[2]) == 4
                            else str(today.year)
                        )
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
                return None, None

        return target_date.strftime("%Y-%m-%d"), time_part


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> None:
    """Validate the user input allows us to connect (Shared validation)."""
    teamname = data[CONF_TEAM_NAME].lower()
    username = data.get(CONF_USERNAME)
    password = data.get(CONF_PASSWORD)

    headers = get_random_headers(teamname)
    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        main_url = f"https://{teamname}.kadermanager.de"

        try:
            headers = {**headers, "Referer": "https://www.kadermanager.de/"}
            async with session.get(
                main_url, timeout=REQUEST_TIMEOUT, headers=headers
            ) as resp:
                if resp.status == 403:
                    _LOGGER.error(
                        "Access forbidden (403) during validation - possibly IP blocked"
                    )
                    raise CannotConnect("IP blocked or access forbidden")
                resp.raise_for_status()
        except Exception as e:
            if not isinstance(e, CannotConnect):
                _LOGGER.error("Validation failed connecting to %s: %s", main_url, e)
                raise CannotConnect from e
            raise

        if username and password:
            login_url = f"{main_url}/sessions/new"
            try:
                await asyncio.sleep(random.uniform(1.0, 3.0))
                async with session.get(
                    login_url, timeout=REQUEST_TIMEOUT, headers=headers
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()

                soup = BeautifulSoup(html, "html.parser")
                token_input = soup.find("input", {"name": "authenticity_token"})
                token_val = ""
                if token_input:
                    t_val = token_input.get("value")
                    token_val = str(
                        t_val[0] if isinstance(t_val, list) else t_val or ""
                    )

                if not token_val:
                    token_meta = soup.find("meta", {"name": "csrf-token"})
                    if token_meta:
                        m_val = token_meta.get("content")
                        token_val = str(
                            m_val[0] if isinstance(m_val, list) else m_val or ""
                        )

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

                # Set referer to login page for the POST
                post_headers = {**headers, "Referer": login_url}
                await asyncio.sleep(random.uniform(1.0, 3.0))
                async with session.post(
                    post_url,
                    data=payload,
                    timeout=REQUEST_TIMEOUT,
                    headers=post_headers,
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        if (
                            "Invalid login" in text
                            or "Anmeldung fehlgeschlagen" in text
                        ):
                            raise InvalidAuth
                    elif resp.status == 403:
                        raise CannotConnect("IP blocked during login")
                    else:
                        raise CannotConnect(f"Login failed with status {resp.status}")
            except (InvalidAuth, CannotConnect):
                raise
            except Exception as e:
                _LOGGER.error("Validation error: %s", e)
                raise CannotConnect from e
