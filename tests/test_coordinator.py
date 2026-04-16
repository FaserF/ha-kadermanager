import pytest
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from custom_components.kadermanager.coordinator import KadermanagerDataUpdateCoordinator


@pytest.fixture
def coordinator():
    hass = MagicMock()
    config = {
        "teamname": "testteam",
        "username": "user",
        "password": "pass",
        "update_interval": 30,
    }
    return KadermanagerDataUpdateCoordinator(hass, config)


def test_parse_date_string(coordinator):
    # Test absolute dates
    date, time = coordinator.parse_date_string("Montag, 01.01.2024 um 19:00")
    assert date == "2024-01-01"
    assert time == "19:00"

    # Test relative dates
    # Mocking datetime.now is tricky, let's check format
    date, time = coordinator.parse_date_string("Heute um 20:00")
    assert time == "20:00"

    date, time = coordinator.parse_date_string("Morgen um 08:00")
    assert time == "08:00"

    # Test year heuristic (Jan 24 if we are in Oct 23)
    with patch("custom_components.kadermanager.coordinator.datetime") as mock_date:
        # Mock today as 2023-10-01
        import datetime

        mock_date.now.return_value = datetime.datetime(2023, 10, 1)
        mock_date.strptime = datetime.datetime.strptime

        # Event is in January
        date, time = coordinator.parse_date_string("01.01.")
        assert "2024" in date  # Should be next year


def test_robust_enrollment_matching(coordinator):
    events_html = """
    <div class="event-detailed-container">
        <a class="event-title-link" href="/events/101">Training</a>
        <h4>Heute um 19:00</h4>
    </div>
    <div class="event-detailed-container">
        <a class="event-title-link" href="https://testteam.kadermanager.de/events/102">Spiel</a>
        <h4>Morgen um 15:00</h4>
    </div>
    """

    home_html = """
    <a href="/events/101">
        <div class="circle-in-enrollments">15</div>
    </a>
    <a href="https://testteam.kadermanager.de/events/102?foo=bar">
        <div class="circle-in-enrollments">11</div>
    </a>
    """

    events = coordinator.parse_events(
        events_html, home_html, "https://testteam.kadermanager.de"
    )

    assert len(events) == 2
    assert events[0]["in_count"] == 15
    assert events[1]["in_count"] == 11


def test_parse_players_and_comments(coordinator):
    html = """
    <div class="drop-zone" id="zone_1">
        <span class="player_label">Player A</span>
        <span class="player_label">Player B</span>
    </div>
    <div class="drop-zone" id="zone_2">
        <span class="player_label">Player C</span>
    </div>
    <div class="message">
        <h5>Author X</h5>
        <p>This is a comment</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")

    players = coordinator.parse_event_players(soup)
    assert "Player A" in players["accepted_players"]
    assert "Player B" in players["accepted_players"]
    assert "Player C" in players["declined_players"]

    comments = coordinator.parse_event_comments(soup)
    assert len(comments) == 1
    assert comments[0]["author"] == "Author X"
    assert comments[0]["text"] == "This is a comment"


def test_calendar_parsing(coordinator):
    from custom_components.kadermanager.calendar import KadermanagerCalendar

    entry = MagicMock()
    entry.data = {"teamname": "test"}
    entry.entry_id = "123"

    calendar = KadermanagerCalendar(coordinator, entry)

    event_data = {
        "date": "2024-05-10",
        "time": "18:30",
        "type": "Training",
        "title": "Evening session",
        "location": "Pitch 1",
        "in_count": 5,
        "link": "http://foo",
    }

    cal_event = calendar._parse_event(event_data)

    assert cal_event.summary == "Training: Evening session"
    assert cal_event.location == "Pitch 1"
    # 2024-05-10 18:30
    assert cal_event.start.year == 2024
    assert cal_event.start.month == 5
    assert cal_event.start.day == 10
    assert cal_event.start.hour == 18
    assert cal_event.start.minute == 30
