import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import asyncio
from custom_components.kadermanager.coordinator import (
    KadermanagerDataUpdateCoordinator,
    get_random_headers,
    USER_AGENTS
)
import aiohttp

class TestScrapingProtection(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.config = {
            "teamname": "testteam",
            "username": "user",
            "password": "pass",
            "update_interval": 30,
        }
        self.coordinator = KadermanagerDataUpdateCoordinator(self.hass, self.config)

    def test_header_generation(self):
        headers = get_random_headers("testteam")
        self.assertIn("User-Agent", headers)
        self.assertIn(headers["User-Agent"], USER_AGENTS)
        self.assertEqual(headers["Referer"], "https://testteam.kadermanager.de/")
        self.assertIn("Accept-Encoding", headers)

    def test_session_header_consistency(self):
        # Create a session and check headers
        with patch('aiohttp.ClientSession') as mock_session:
            asyncio.run(self.coordinator._async_scrape_data())
            # Check that the session was created with the coordinator's headers
            mock_session.assert_called_once()
            args, kwargs = mock_session.call_args
            self.assertEqual(kwargs['headers'], self.coordinator._headers)

    @patch("custom_components.kadermanager.coordinator.datetime")
    def test_progressive_backoff_on_block(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0)
        
        # Simulate a 403 block
        err = aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=403)
        
        with patch.object(self.coordinator, "_async_scrape_data", side_effect=err):
            with self.assertRaises(Exception):
                asyncio.run(self.coordinator._async_update_data())
        
        self.assertEqual(self.coordinator._consecutive_failures, 1)
        # 1st failure = 2 hours backoff
        self.assertEqual(self.coordinator._backoff_until, datetime(2024, 1, 1, 14, 0, 0))
        
        # Simulate second 403 block
        mock_datetime.now.return_value = datetime(2024, 1, 1, 14, 0, 1)
        with patch.object(self.coordinator, "_async_scrape_data", side_effect=err):
            with self.assertRaises(Exception):
                asyncio.run(self.coordinator._async_update_data())
        
        self.assertEqual(self.coordinator._consecutive_failures, 2)
        # 2nd failure = 4 hours backoff
        self.assertEqual(self.coordinator._backoff_until, datetime(2024, 1, 1, 18, 0, 1))

    @patch("custom_components.kadermanager.coordinator.datetime")
    def test_backoff_on_connection_error(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0, 0)
        
        # Simulate connection error
        err = aiohttp.ClientConnectorError(MagicMock(), MagicMock())
        
        with patch.object(self.coordinator, "_async_scrape_data", side_effect=err):
            with self.assertRaises(Exception):
                asyncio.run(self.coordinator._async_update_data())
        
        self.assertEqual(self.coordinator._consecutive_failures, 1)
        # 1st failure = 60 minutes backoff
        self.assertEqual(self.coordinator._backoff_until, datetime(2024, 1, 1, 13, 0, 0))

if __name__ == "__main__":
    unittest.main()
