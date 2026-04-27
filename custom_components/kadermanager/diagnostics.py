"""Diagnostics support for Kadermanager."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.loader import async_get_integration

from .const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_TEAM_NAME,
    CONF_EVENT_LIMIT,
    CONF_UPDATE_INTERVAL,
    CONF_FETCH_PLAYER_INFO,
    CONF_FETCH_COMMENTS,
    DOMAIN,
)
from .coordinator import KadermanagerDataUpdateCoordinator

# Fields to strip from diagnostic output before handing to the user
TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "password", "username", "email"}


def _summarise_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a privacy-safe summary of the cached event list.

    Player names and comments are intentionally omitted; only aggregate
    counts and date ranges are included so they cannot be used to identify
    individuals.
    """
    if not events:
        return {"count": 0}

    type_counts: dict[str, int] = {}
    dates: list[str] = []
    player_count_total = 0

    for event in events:
        event_type = event.get("type", "Unknown")
        type_counts[event_type] = type_counts.get(event_type, 0) + 1

        date = event.get("date")
        if date and date != "Unknown":
            dates.append(date)

        players = event.get("players", {})
        player_count_total += len(players.get("accepted_players", []))

    return {
        "count": len(events),
        "type_counts": type_counts,
        "earliest_date": min(dates) if dates else None,
        "latest_date": max(dates) if dates else None,
        "total_accepted_players_across_events": player_count_total,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: KadermanagerDataUpdateCoordinator | None = (
        hass.data.get(DOMAIN, {}).get(entry.entry_id)
    )

    # ── Environment ──────────────────────────────────────────────────────────
    integration = await async_get_integration(hass, DOMAIN)
    diag: dict[str, Any] = {
        "home_assistant_version": HA_VERSION,
        "integration_version": integration.version,
    }

    # ── Config entry (secrets redacted) ──────────────────────────────────────
    diag["config_entry"] = async_redact_data(entry.as_dict(), TO_REDACT)

    # ── Parsed options (for quick human reading) ──────────────────────────────
    config = {**entry.data, **entry.options}
    diag["config_options"] = {
        "teamname": config.get(CONF_TEAM_NAME, "unknown"),
        "has_credentials": bool(
            config.get(CONF_USERNAME) and config.get(CONF_PASSWORD)
        ),
        "event_limit": config.get(CONF_EVENT_LIMIT, 5),
        "update_interval_minutes": config.get(CONF_UPDATE_INTERVAL, 30),
        "fetch_player_info": config.get(CONF_FETCH_PLAYER_INFO, False),
        "fetch_comments": config.get(CONF_FETCH_COMMENTS, False),
    }

    # ── Coordinator state ─────────────────────────────────────────────────────
    if coordinator is None:
        diag["coordinator"] = "not_initialized"
        return diag

    last_exception = coordinator.last_exception
    raw_events: list[dict[str, Any]] = (
        (coordinator.data or {}).get("events") or []
    )

    diag["coordinator"] = {
        # Connection health
        "last_update_success": coordinator.last_update_success,
        "last_success_at": (
            coordinator.last_success.isoformat() if coordinator.last_success else None
        ),
        "last_exception": str(last_exception) if last_exception else None,
        # Session / auth state
        "logged_in": coordinator._logged_in,
        "session_open": (
            coordinator._session is not None
            and not coordinator._session.closed
        ),
        "backoff_active": coordinator._backoff_until is not None,
        "backoff_until": (
            coordinator._backoff_until.isoformat()
            if coordinator._backoff_until
            else None
        ),
        "issue_reported": coordinator._issue_created,
        # Timing
        "update_interval": str(coordinator.update_interval),
        # Data summary (privacy-safe – no names, no comments)
        "cached_events_summary": _summarise_events(raw_events),
        "general_comments_cached": len(
            (coordinator.data or {}).get("general_comments") or []
        ),
    }

    return diag
