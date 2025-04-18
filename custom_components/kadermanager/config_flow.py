import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_TEAM_NAME,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    CONF_EVENT_LIMIT,
    CONF_FETCH_PLAYER_INFO,
    CONF_FETCH_COMMENTS,
)

_LOGGER = logging.getLogger(__name__)

class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""

        def __get_option(key: str, default: Any) -> Any:
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_TEAM_NAME])
            self._abort_if_unique_id_configured()
            _LOGGER.debug("Initialized new kadermanager with id: %s", user_input[CONF_TEAM_NAME])
            return self.async_create_entry(title=user_input[CONF_TEAM_NAME], data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TEAM_NAME, default=__get_option(CONF_TEAM_NAME, "")): str,
                    vol.Optional(CONF_USERNAME, default=__get_option(CONF_USERNAME, "")): str,
                    vol.Optional(CONF_PASSWORD, default=__get_option(CONF_PASSWORD, "")): str,
                    vol.Required(CONF_UPDATE_INTERVAL, default=__get_option(CONF_UPDATE_INTERVAL, 30)): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                    vol.Required(CONF_EVENT_LIMIT, default=__get_option(CONF_EVENT_LIMIT, 3)): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
                    vol.Required(CONF_FETCH_PLAYER_INFO, default=__get_option(CONF_FETCH_PLAYER_INFO, True)): bool,
                    vol.Required(CONF_FETCH_COMMENTS, default=__get_option(CONF_FETCH_COMMENTS, True)): bool,
                },
            ),
        )

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow"""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_TEAM_NAME])
            self._abort_if_unique_id_configured()

            _LOGGER.debug("Initialized new kadermanager with id: %s", user_input[CONF_TEAM_NAME])

            return self.async_create_entry(title=user_input[CONF_TEAM_NAME], data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_TEAM_NAME): str,
                vol.Optional(CONF_USERNAME): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Required(CONF_UPDATE_INTERVAL, default=30): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                vol.Required(CONF_EVENT_LIMIT, default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
                vol.Required(CONF_FETCH_PLAYER_INFO, default=True): bool,
                vol.Required(CONF_FETCH_COMMENTS, default=True): bool,
            },
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)
