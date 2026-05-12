import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta
import asyncio
import aiohttp
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from custom_components.kadermanager.coordinator import (
    KadermanagerDataUpdateCoordinator,
    get_random_headers,
)


class TestScrapingProtection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = MagicMock()
        # Mock the scrape_lock to avoid issues with Lock()
        self.hass.data = {"kadermanager": {"scrape_lock": asyncio.Lock()}}
        self.entry = MagicMock()
        self.entry.data = {
            "teamname": "testteam",
            "username": "user",
            "password": "password",
        }
        self.entry.options = {"update_interval": 60}
        self.coordinator = KadermanagerDataUpdateCoordinator(self.hass, self.entry)
        self.coordinator.store = MagicMock()
        self.coordinator.store.async_save = AsyncMock()

    def test_header_generation(self):
        headers = get_random_headers("testteam")
        self.assertIn("User-Agent", headers)

    @patch("custom_components.kadermanager.coordinator.dt_util.now")
    async def test_progressive_backoff_on_block(self, mock_now):
        now_val = datetime(2024, 1, 1, 12, 0, 0)
        mock_now.return_value = now_val

        # Simulate a 403 block using a custom exception with status
        class MockResponseError(Exception):
            status = 403
        err = MockResponseError()

        # Mock internal methods to avoid side effects
        with patch.object(self.coordinator, "_async_scrape_data", side_effect=err):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with self.assertRaises(UpdateFailed):
                    await self.coordinator._async_update_data()

        self.assertEqual(self.coordinator._consecutive_failures, 1)
        self.assertEqual(self.coordinator._backoff_until, now_val + timedelta(hours=2))

    @patch("custom_components.kadermanager.coordinator.dt_util.now")
    async def test_backoff_on_connection_error(self, mock_now):
        now_val = datetime(2024, 1, 1, 12, 0, 0)
        mock_now.return_value = now_val

        # Simulate connection error
        err = aiohttp.ClientConnectorError(MagicMock(), MagicMock())

        # Mock internal methods to avoid side effects
        with patch.object(self.coordinator, "_async_scrape_data", side_effect=err):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with self.assertRaises(UpdateFailed):
                    await self.coordinator._async_update_data()

        self.assertEqual(self.coordinator._consecutive_failures, 1)
        self.assertEqual(self.coordinator._backoff_until, now_val + timedelta(minutes=60))
