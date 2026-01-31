import logging
from typing import Any
import requests
from bs4 import BeautifulSoup
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

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
REQUEST_TIMEOUT = 15

class CannotConnect(Exception):
    """Error to indicate we cannot connect."""

class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""

def _login(session: requests.Session, login_url: str, username: str, password: str) -> bool:
    """Perform login. Returns True if successful."""
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
                _LOGGER.error("Login failed during validation.")
                return False
            else:
                _LOGGER.debug("Login successful.")
                return True
        return False

    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")
        return False

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate the user input allows us to connect."""
    teamname = data[CONF_TEAM_NAME]
    username = data.get(CONF_USERNAME)
    password = data.get(CONF_PASSWORD)

    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT})

    main_url = f"https://{teamname}.kadermanager.de"

    try:
        response = await hass.async_add_executor_job(session.get, main_url)
        response.raise_for_status()
    except Exception as e:
        _LOGGER.error(f"Validation failed connecting to {main_url}: {e}")
        raise CannotConnect from e

    if username and password:
        login_url = f"https://{teamname}.kadermanager.de/sessions/new"
        success = await hass.async_add_executor_job(_login, session, login_url, username, password)
        if not success:
            raise InvalidAuth

class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""

        def __get_option(key: str, default: Any) -> Any:
            return self._config_entry.options.get(
                key, self._config_entry.data.get(key, default)
            )

        if user_input is not None:
            # We also validate in options flow? Optional but good.
            # For now just save.
            # await self.async_set_unique_id(user_input[CONF_TEAM_NAME])
            # Note: Changing team name in options is tricky for unique_id.
            # Assuming user keeps team name or we don't allow changing it easily?
            # Existing logic allowed it.

            return self.async_create_entry(title=user_input.get(CONF_TEAM_NAME, ""), data=user_input)

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

            try:
                await validate_input(self.hass, user_input)

                _LOGGER.debug("Initialized new kadermanager with id: %s", user_input[CONF_TEAM_NAME])
                return self.async_create_entry(title=user_input[CONF_TEAM_NAME], data=user_input)

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception: # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

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
