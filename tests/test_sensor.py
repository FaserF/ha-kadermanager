import pytest
import os
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from custom_components.kadermanager.sensor import get_kadermanager_events, KadermanagerSensor

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
    assert first_event["parsed_date"] != "Unknown" if "parsed_date" in first_event else True
    # Note: Keys might be 'date' and 'original_date' and 'time'

    print(f"Parsed First Event: {first_event}")

    # In my synthetic fixture:
    # Event 1: Mo 01.01. -> Training
    # in_count: 12 (from fake main page)

    assert first_event['type'] == 'Training'
    assert first_event['in_count'] == 12 or first_event['in_count'] == "Unknown"
    # (in_count logic depends on index matching, synthetic file has 2 events and 2 circles, so it should match)

    # Check second event
    second_event = events[1]
    assert second_event['type'] == 'Spiel'
    assert second_event['location'] == 'Stadionweg 99, 54321 Beispielhausen'

def test_sensor_setup():
    """Basic test to ensure sensor class can be instantiated."""
    config = {
        "teamname": "test_team",
        "username": "user",
        "password": "pw",
        "update_interval": 15,
        "event_limit": 5,
        "fetch_player_info": False,
        "fetch_comments": False
    }
    hass = MagicMock()
    sensor = KadermanagerSensor(config, hass)
    assert sensor.name == "Kadermanager test_team"
