"""Diagnostics support for Kadermanager."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import KadermanagerDataUpdateCoordinator

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "password", "username", "email"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: KadermanagerDataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    diag_data = {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
    }

    if coordinator:
        diag_data["coordinator_data"] = async_redact_data(coordinator.data or {}, TO_REDACT)
        diag_data["coordinator_state"] = {
            "last_success": coordinator.last_success.isoformat() if coordinator.last_success else None,
            "logged_in": coordinator._logged_in,
            "backoff_until": coordinator._backoff_until.isoformat() if coordinator._backoff_until else None,
            "teamname": coordinator.teamname,
            "update_interval": str(coordinator.update_interval),
        }
    else:
        diag_data["coordinator_state"] = "not_initialized"

    return diag_data
