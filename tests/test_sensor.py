import pytest
import os
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from custom_components.kadermanager.coordinator import get_kadermanager_events, KadermanagerDataUpdateCoordinator
from custom_components.kadermanager.sensor import KadermanagerSensor
from custom_components.kadermanager.const import CONF_TEAM_NAME

# We need to mock requests to return our local file content
@pytest.fixture
def mock_html_content():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "kadermanager_events.html")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return f.read()

def test_parsing_logic(mock_html_content):
    """Test that the scraping logic correctly parses the valid HTML."""

    # Create a mock session
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.text = mock_html_content
    mock_response.status_code = 200
    mock_session.get.return_value = mock_response

    events = get_kadermanager_events(mock_session, "http://mock/events", "http://mock/main")

    assert len(events) > 0
    first_event = events[0]

    assert "date" in first_event, "Event should have a date"
    # Coordinator returns 'date' (ISO)
    assert first_event["date"] != "Unknown"

    print(f"Parsed First Event: {first_event}")

    # In my synthetic fixture:
    # Event 1: Mo 01.01. -> Training
    # in_count: 12 (from fake main page)

    assert first_event['type'] == 'Training'
    assert first_event['in_count'] == 12 or first_event['in_count'] == "Unknown"

    # Check second event
    second_event = events[1]
    assert second_event['type'] == 'Spiel'
    assert second_event['location'] == 'Stadionweg 99, 54321 Beispielhausen'

def test_sensor_setup():
    """Basic test to ensure sensor class can be instantiated with coordinator."""
    # Mock Config Entry
    config_entry = MagicMock()
    config_entry.data = {
        CONF_TEAM_NAME: "test_team"
    }
    config_entry.entry_id = "123"

    # Mock Coordinator
    coordinator = MagicMock()
    coordinator.data = {'events': []}

    # Instantiate Sensor
    sensor = KadermanagerSensor(coordinator, config_entry)

    assert sensor.name == "Kadermanager test_team"
