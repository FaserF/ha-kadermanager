import sys
from unittest.mock import MagicMock

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
update_coordinator_mock.CoordinatorEntity = MagicMock
update_coordinator_mock.DataUpdateCoordinator = MagicMock
update_coordinator_mock.UpdateFailed = Exception

# Other mocks
sys.modules["homeassistant.util"] = MagicMock()
sys.modules["homeassistant.util.dt"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["async_timeout"] = MagicMock()

# Define SensorEntity since it's used as a base class
class MockSensorEntity:
    def __init__(self):
        self._attr_extra_state_attributes = {}

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes

ha_sensor_mock = sys.modules["homeassistant.components.sensor"]
ha_sensor_mock.SensorEntity = MockSensorEntity
