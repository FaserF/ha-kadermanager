import logging
from datetime import datetime, timedelta
from typing import Optional

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_TEAM_NAME
from .coordinator import KadermanagerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Kadermanager calendar platform."""
    coordinator: KadermanagerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KadermanagerCalendar(coordinator, entry)], True)


class KadermanagerCalendar(CoordinatorEntity, CalendarEntity):
    """Kadermanager Calendar Entity."""

    def __init__(self, coordinator: KadermanagerDataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self.teamname = entry.data[CONF_TEAM_NAME]
        self._name = f"Kadermanager {self.teamname}"
        self._unique_id = f"{self.teamname}_calendar"
        self._event: Optional[CalendarEvent] = None

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the entity."""
        return self._unique_id

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

    @property
    def event(self) -> Optional[CalendarEvent]:
        """Return the next upcoming event."""
        # This property is legacy/for state display, usually the next upcoming event.
        # We can implement it by grabbing the first event from coordinator that is in the future.
        if not self.coordinator.data or not self.coordinator.data.get("events"):
            return None

        # We assume the list is sorted by date by the website/scraper
        first_event_data = self.coordinator.data["events"][0]
        return self._parse_event(first_event_data)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        if not self.coordinator.data or not self.coordinator.data.get("events"):
            return []

        events = []
        for event_data in self.coordinator.data["events"]:
            cal_event = self._parse_event(event_data)
            if cal_event and convert_to_datetime(cal_event.start) >= start_date and convert_to_datetime(cal_event.end) <= end_date:
                events.append(cal_event)
            # Also include if it overlaps? Usually strict range check is fine or overlap check.
            # Simple check: start < end_range AND end > start_range
            elif cal_event:
                 s = convert_to_datetime(cal_event.start)
                 e = convert_to_datetime(cal_event.end)
                 if s < end_date and e > start_date:
                     events.append(cal_event)

        return events

    def _parse_event(self, event_data: dict) -> Optional[CalendarEvent]:
        """Convert scraped data to CalendarEvent."""
        try:
            date_str = event_data.get("date") # YYYY-MM-DD
            time_str = event_data.get("time") # HH:MM or Unknown

            if not date_str or date_str == "Unknown":
                return None

            # Helper to combine
            if time_str and time_str != "Unknown":
                 dt_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                 # Assume 2 hours duration by default
                 dt_end = dt_start + timedelta(hours=2)
            else:
                 # All day event if time is unknown? Or default to 00:00?
                 # CalendarEntity supports date-only (all day).
                 # If time is missing, let's make it all day.
                 dt_start = datetime.strptime(date_str, "%Y-%m-%d").date()
                 dt_end = dt_start + timedelta(days=1)

            summary = f"{event_data.get('type', 'Event')}: {event_data.get('title', '')}"
            description = (
                f"Location: {event_data.get('location', '')}\n"
                f"In: {event_data.get('in_count', '')}\n"
                f"Link: {event_data.get('link', '')}"
            )

            return CalendarEvent(
                summary=summary,
                start=dt_start,
                end=dt_end,
                description=description,
                location=event_data.get('location')
            )
        except Exception as e:
            _LOGGER.error(f"Error parsing calendar event: {e}")
            return None

def convert_to_datetime(val):
    """Helper to ensure comparison works for date and datetime."""
    if isinstance(val, datetime):
        return val
    return datetime(val.year, val.month, val.day)
