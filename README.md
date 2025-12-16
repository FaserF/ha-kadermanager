[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Kadermanager Home Assistant Integration ⚽

The `kadermanager` integration retrieves event and participant information from [Kadermanager](https://kadermanager.de/).

<img src="https://assets1.nimenhuuto.com/assets/logos/kadermanager.de/logo_h128-9f99c175236041ce4e42e770ed364faad6945c046539b14d1828720df6baa426.png" alt="Kadermanager" width="300px">
<img src="images/sensor.png" alt="Kadermanager Sensor" width="300px">

## Features ✨

- **Event Tracking**: See upcoming games/trainings, dates, and locations.
- **Participation Stats**: Monitor how many people accepted or declined.
- **Comments**: View latest comments on events.

## Installation 🛠️

### 1. Using HACS (Recommended)

This integration works as a **Custom Repository** in HACS.

1.  Open HACS.
2.  Add Custom Repository: `https://github.com/FaserF/ha-kadermanager` (Category: Integration).
3.  Click **Download**.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=FaserF&repository=ha-kadermanager&category=integration)

### 2. Manual Installation

1.  Download the latest [Release](https://github.com/FaserF/ha-kadermanager/releases/latest).
2.  Extract the ZIP file.
3.  Copy the `kadermanager` folder to `<config>/custom_components/`.

## Configuration ⚙️

1.  Go to **Settings** -> **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for "Kadermanager".

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kadermanager)

### Configuration Variables
- **Team Name**: Your subdomain (e.g., `teamname` for `teamname.kadermanager.de`).
- **Additional Settings**: Refresh interval, event limits, comment fetching.

## Sensor Attributes
The data is being refreshed every 30 minutes per default, unless otherwise defined in the refresh time.

### General attributes
- events:
  - original_date: Displays the Date and Time for the event
  - comments: Displays event specific comments
    - text
    - author
  - date: extracted date from original_date
  - time: extraced time from original_date
  - in_count: Current count of people in for the event
  - title: Event title (will be filled with the type if empty)
  - type: Event type (training/game/other)
  - link: Link to the event
  - location: Location of the event

### Attributes available with sign in / public events
Those data will only be fetched for the next upcoming event.

Currently signing in wont work, as bots seem to be blocked. But you can check your events to be public readable, then the following data can also be fetched:

- events:
  - players:
    - accepted_players (will only be fetched if "fetch player info" is turned on): Players that accepted the event
    - declined_players (will only be fetched if "fetch player info" is turned on): Players that declined the event
    - no_response_players (will only be fetched if "fetch player info" is turned on): Players that gave no response if they are attending or not

- events:
  - comments:
    - author: player that has written the comment
    - text: Text written in the comment

### Attributes available with sign in (doesnt matter if events are public)
Currently signing in wont work, as bots seem to be blocked.
- comments: Displays all general comments from the main page, which are not event related

## Automation example
Send a reminder for the next event two days before

```yaml
automation:
  - alias: "Reminder for Kadermanager event two days before"
    trigger:
      - platform: template
        value_template: "{{ as_timestamp(states.sensor.kadermanager_teamname.attributes.events[0].date) - as_timestamp(now()) <= 2 * 24 * 3600 }}"
    condition:
      - condition: template
        value_template: "{{ states.sensor.kadermanager_teamname.attributes.events }}"
    action:
      - service: notify.notify
        data_template:
          title: "Upcoming kadermanager event"
          message: >
            The next Kadermanager event is coming:
            Type: {{ states.sensor.kadermanager_teamname.attributes.events[0].type }}
            Titel: {{ states.sensor.kadermanager_teamname.attributes.events[0].title }}
            Accepted Count: {{ states.sensor.kadermanager_teamname.attributes.events[0].in_count }}
            Who has declined: {{ states.sensor.kadermanager_teamname.attributes.events[0].players.declined_players | join(', ') }}
```

Send a message if a new kadermanager event has been written
```yaml
automation:
  - alias: "Notification on New Comment"
    trigger:
      - platform: state
        entity_id: sensor.kadermanager_teamname
    condition:
      # Check if the comment has changed
      condition: template
      value_template: >
        {% set old_comments = trigger.from_state.attributes.events[0].comments if trigger.from_state.attributes.events else [] %}
        {% set new_comments = trigger.to_state.attributes.events[0].comments if trigger.to_state.attributes.events else [] %}
        {{ new_comments | length > old_comments | length }}
    action:
      - service: notify.notify
        data:
          message: >
            New comment by {{ states.sensor.kadermanager_teamname.attributes.events[0].comments[0].author }}:
            {{ states.sensor.kadermanager_teamname.attributes.events[0].comments[0].text }}
```

## Bug reporting
Open an issue over at [github issues](https://github.com/FaserF/ha-kadermanager/issues). Please prefer sending over a log with debugging enabled.

To enable debugging enter the following in your configuration.yaml

```yaml
logger:
    logs:
        custom_components.kadermanager: debug
```

You can then find the log in the HA settings -> System -> Logs -> Enter "kadermanager" in the search bar -> "Load full logs"

## Thanks to
Thanks to Kadermanager for their great free software!

The data is coming from the [kadermanager.de](https://kadermanager.de/) website.
