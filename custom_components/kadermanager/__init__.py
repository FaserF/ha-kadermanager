import logging
from homeassistant import config_entries, core
from homeassistant.const import CONF_NAME

from .const import DOMAIN, PLATFORMS
from .coordinator import KadermanagerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry):
    """Set up platform from a ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})

    config = entry.data
    if entry.options:
        config.update(entry.options)

    coordinator = KadermanagerDataUpdateCoordinator(hass, config)

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok