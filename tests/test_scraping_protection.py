import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta
import asyncio
import aiohttp
from custom_components.kadermanager.coordinator import (
    KadermanagerDataUpdateCoordinator,
    get_random_headers,
)


class TestScrapingProtection(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        # Mock the scrape_lock to avoid issues with Lock()
        self.hass.data = {"kadermanager": {"scrape_lock": AsyncMock()}}
        self.entry = MagicMock()
        self.entry.data = {
            "teamname": "testteam",
            "username": "user",
            "password": "pass",
        }
        self.entry.options = {
            "update_interval": 60,
        }
        with patch(
            "homeassistant.util.dt.now", return_value=datetime(2024, 1, 1, 12, 0, 0)
        ):
            self.coordinator = KadermanagerDataUpdateCoordinator(self.hass, self.entry)

    def test_header_generation(self):
        headers = get_random_headers("testteam")
        self.assertIn("User-Agent", headers)

    @patch("homeassistant.util.dt.now")
    def test_progressive_backoff_on_block(self, mock_now):
        now_val = datetime(2024, 1, 1, 12, 0, 0)
        mock_now.return_value = now_val

        # Simulate a 403 block
        err = aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=403)

        # Mock internal methods to avoid side effects
        with patch.object(self.coordinator, "_async_scrape_data", side_effect=err):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # We expect UpdateFailed (which is Exception in tests)
                with self.assertRaises(Exception):
                    asyncio.run(self.coordinator._async_update_data())

        self.assertEqual(self.coordinator._consecutive_failures, 1)
        self.assertEqual(self.coordinator._backoff_until, now_val + timedelta(hours=2))

    @patch("homeassistant.util.dt.now")
    def test_backoff_on_connection_error(self, mock_now):
        now_val = datetime(2024, 1, 1, 12, 0, 0)
        mock_now.return_value = now_val

        # Simulate connection error
        err = aiohttp.ClientConnectorError(MagicMock(), MagicMock())

        with patch.object(self.coordinator, "_async_scrape_data", side_effect=err):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with self.assertRaises(Exception):
                    asyncio.run(self.coordinator._async_update_data())

        self.assertEqual(self.coordinator._consecutive_failures, 1)
        self.assertEqual(
            self.coordinator._backoff_until, now_val + timedelta(minutes=60)
        )


if __name__ == "__main__":
    unittest.main()
