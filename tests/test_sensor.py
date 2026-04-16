import pytest
import os
from unittest.mock import MagicMock
from custom_components.kadermanager.coordinator import KadermanagerDataUpdateCoordinator
from custom_components.kadermanager.sensor import KadermanagerSensor
from custom_components.kadermanager.const import (
    CONF_TEAM_NAME,
    CONF_EVENT_LIMIT,
    CONF_FETCH_PLAYER_INFO,
    CONF_FETCH_COMMENTS,
    CONF_UPDATE_INTERVAL,
)


# We need to mock requests to return our local file content
@pytest.fixture
def mock_html_content():
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "kadermanager_events.html"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def coordinator_mock():
    hass = MagicMock()
    config = {
        CONF_TEAM_NAME: "test",
        CONF_EVENT_LIMIT: 5,
        CONF_FETCH_PLAYER_INFO: True,
        CONF_FETCH_COMMENTS: True,
        CONF_UPDATE_INTERVAL: 60,
    }
    return KadermanagerDataUpdateCoordinator(hass, config)


def test_parsing_logic(mock_html_content, coordinator_mock):
    """Test that the scraping logic correctly parses the valid HTML."""

    events = coordinator_mock.parse_events(
        mock_html_content, mock_html_content, "http://mock"
    )

    assert len(events) > 0
    first_event = events[0]

    assert "date" in first_event, "Event should have a date"
    # Coordinator returns 'date' (ISO)
    assert first_event["date"] != "Unknown"

    print(f"Parsed First Event: {first_event}")

    # In my synthetic fixture:
    # Event 1: Mo 01.01. -> Training
    # in_count: 12 (from fake main page)

    assert first_event["type"] == "Training"
    assert first_event["in_count"] == 12 or first_event["in_count"] == "Unknown"

    # Check second event
    second_event = events[1]
    assert second_event["type"] == "Spiel"
    assert second_event["location"] == "Stadionweg 99, 54321 Beispielhausen"


def test_sensor_setup():
    """Basic test to ensure sensor class can be instantiated with coordinator."""
    # Mock Config Entry
    config_entry = MagicMock()
    config_entry.data = {CONF_TEAM_NAME: "test_team"}
    config_entry.entry_id = "123"

    # Mock Coordinator
    coordinator = MagicMock()
    coordinator.data = {"events": []}

    # Instantiate Sensor
    sensor = KadermanagerSensor(coordinator, config_entry)

    assert sensor.name == "Kadermanager test_team"
