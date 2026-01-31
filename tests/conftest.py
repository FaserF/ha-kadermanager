import sys
from unittest.mock import MagicMock
import datetime

# Create a mock for the base homeassistant package
ha_mock = MagicMock()
sys.modules["homeassistant"] = ha_mock

# Helper mocks
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.config_validation"] = MagicMock()
sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.typing"] = MagicMock()

# Update Coordinator
update_coordinator_mock = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_mock

# Define a proper dummy class for CoordinatorEntity
class MockCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.last_update_success = True

# Define a proper dummy class for DataUpdateCoordinator
class MockDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval):
        self.data = {}

update_coordinator_mock.CoordinatorEntity = MockCoordinatorEntity
update_coordinator_mock.DataUpdateCoordinator = MockDataUpdateCoordinator
update_coordinator_mock.UpdateFailed = Exception

# Other mocks
util_mock = MagicMock()
sys.modules["homeassistant.util"] = util_mock

dt_mock = MagicMock()
sys.modules["homeassistant.util.dt"] = dt_mock
# Link them
util_mock.dt = dt_mock
# Mock DEFAULT_TIME_ZONE
dt_mock.DEFAULT_TIME_ZONE = datetime.timezone.utc

sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = MagicMock()
sys.modules["homeassistant.components.calendar"] = MagicMock() # Added for calendar
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["async_timeout"] = MagicMock()

# Define SensorEntity since it's used as a base class
class MockSensorEntity:
    def __init__(self):
        self._attr_extra_state_attributes = {}

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes

# Define CalendarEntity
class MockCalendarEntity:
    def __init__(self):
        pass

ha_sensor_mock = sys.modules["homeassistant.components.sensor"]
ha_sensor_mock.SensorEntity = MockSensorEntity

ha_calendar_mock = sys.modules["homeassistant.components.calendar"]
ha_calendar_mock.CalendarEntity = MockCalendarEntity
ha_calendar_mock.CalendarEvent = MagicMock
