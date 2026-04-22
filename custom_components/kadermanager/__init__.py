import logging
from homeassistant import config_entries, core

from homeassistant.exceptions import ConfigEntryNotReady
from .const import DOMAIN, PLATFORMS
from .coordinator import KadermanagerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    """Set up platform from a ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})

    config = {**entry.data, **entry.options}

    coordinator = KadermanagerDataUpdateCoordinator(hass, config)
    await coordinator.async_load_cache()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed:
        # We still want to continue to allow diagnostics and options updates if possible,
        # but HA expects an error or success here. 
        # If we raise ConfigEntryNotReady, HA will retry.
        pass

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_update_options(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    """Unload a config entry."""
    coordinator: KadermanagerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_close()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
