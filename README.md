[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Kadermanager Home Assistant Integration ⚽

The `kadermanager` integration retrieves event and participant information from [Kadermanager](https://kadermanager.de/).

<img src="https://assets1.nimenhuuto.com/assets/logos/kadermanager.de/logo_h128-9f99c175236041ce4e42e770ed364faad6945c046539b14d1828720df6baa426.png" alt="Kadermanager" width="300px">
<img src="images/sensor.png" alt="Kadermanager Sensor" width="300px">

## Features ✨

- **Event Tracking**: See upcoming games/trainings, dates, and locations.
- **Participation Stats**: Monitor how many people accepted or declined.
- **Comments**: View latest comments on events.
- **Robustness**: Uses browser sessions and headers to avoid blocking.
- **Authentication**: Supports login to fetch internal team events.
- **Self-Repair**: Automatically detects persistent failures (>24h) and creates a generic Repair issue in Home Assistant.

## Installation 🛠️

### 1. Using HACS (Recommended)

This integration works as a **Custom Repository** in HACS.

1.  Open HACS.
2.  Add Custom Repository: `https://github.com/FaserF/ha-kadermanager` (Category: Integration).
3.  Click **Download**.
4.  Restart Home Assistant.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=FaserF&repository=ha-kadermanager&category=integration)

### 2. Manual Installation

1.  Download the latest [Release](https://github.com/FaserF/ha-kadermanager/releases/latest).
2.  Extract the ZIP file.
3.  Copy the `kadermanager` folder to `<config>/custom_components/`.
4.  Restart Home Assistant.

## Configuration ⚙️

1.  Go to **Settings** -> **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for "Kadermanager".

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kadermanager)

### Configuration Variables
- **Team Name**: Your subdomain (e.g., `teamname` for `teamname.kadermanager.de`).
- **Username/Password**: (Optional) Providing credentials allows the integration to log in and fetch non-public events/details.
- **Additional Settings**: Refresh interval, event limits, comment fetching.

## Sensor Attributes
The data is being refreshed every 30 minutes by default.

### General attributes
- events:
  - original_date: Displays the Date and Time for the event
  - comments: Displays event specific comments (author, text)
  - date: extracted date (ISO format)
  - time: extracted time
  - in_count: Current count of people in for the event
  - title: Event title
  - type: Event type (Training/Spiel/Sonstiges)
  - link: Link to the event
  - location: Location of the event

### Attributes available with public events
If your events are public, the following data can also be fetched:

- events:
  - players:
    - accepted_players: Players that accepted
    - declined_players: Players that declined
    - no_response_players: Players that gave no response

## Troubleshooting ⚠️

### Status "Unknown"
If the sensor status shows "Unknown":
1.  **Check Team Name**: Ensure your team name corresponds exactly to the subdomain (e.g., `https://myteam.kadermanager.de` -> `myteam`).
2.  **Access/Login**: Ensure your "Events" page allows public viewing OR that you have provided valid username/password in the configuration. The integration attempts to log in if credentials are provided.
3.  **Logs**: Enable debug logging to see what the scraper is receiving.

```yaml
logger:
    logs:
        custom_components.kadermanager: debug
```

## Automation Examples 🤖

<details>
<summary><b>📅 Reminder: Upcoming Event (2 days before)</b></summary>

Send a notification 48 hours before the next event starts.

```yaml
automation:
  - alias: "Kadermanager Reminder - 2 Days Warning"
    trigger:
      - platform: template
        value_template: "{{ as_timestamp(state_attr('sensor.kadermanager_teamname', 'events')[0].date) - as_timestamp(now()) <= 2 * 24 * 3600 }}"
    condition:
      - condition: template
        value_template: "{{ state_attr('sensor.kadermanager_teamname', 'events') }}"
    action:
      - service: notify.notify
        data_template:
          title: "Upcoming Event"
          message: >
            Next Event: {{ state_attr('sensor.kadermanager_teamname', 'events')[0].title }}
            Date: {{ state_attr('sensor.kadermanager_teamname', 'events')[0].original_date }}
            Participants: {{ state_attr('sensor.kadermanager_teamname', 'events')[0].in_count }}
```
</details>

<details>
<summary><b>⚠️ Alert: Low Participation Count</b></summary>

Warn if less than 6 players are signed up 24 hours before a game.

```yaml
automation:
  - alias: "Kadermanager - Low Participation Warning"
    trigger:
      - platform: template
        value_template: "{{ as_timestamp(state_attr('sensor.kadermanager_teamname', 'events')[0].date) - as_timestamp(now()) < 24 * 3600 }}"
    condition:
      # Ensure there are events
      - condition: template
        value_template: "{{ state_attr('sensor.kadermanager_teamname', 'events') }}"
      # Check it is a Game ("Spiel")
      - condition: template
        value_template: "{{ state_attr('sensor.kadermanager_teamname', 'events')[0].type == 'Spiel' }}"
      # Check count safe casting to int
      - condition: template
        value_template: "{{ state_attr('sensor.kadermanager_teamname', 'events')[0].in_count | int(0) < 6 }}"
    action:
      - service: notify.notify
        data:
          title: "Low Player Count!"
          message: "Warning: Only {{ state_attr('sensor.kadermanager_teamname', 'events')[0].in_count }} players for tomorrow's game!"
```
</details>

<details>
<summary><b>💬 Notification: New Comment Posted</b></summary>

Get notified when a teammate writes a new comment.

```yaml
automation:
  - alias: "Notification on New Comment"
    trigger:
      - platform: state
        entity_id: sensor.kadermanager_teamname
    condition:
      - condition: template
        value_template: >
          {% set old_comments = trigger.from_state.attributes.events[0].comments if trigger.from_state.attributes.events else [] %}
          {% set new_comments = trigger.to_state.attributes.events[0].comments if trigger.to_state.attributes.events else [] %}
          {{ new_comments | length > old_comments | length }}
    action:
      - service: notify.notify
        data:
          message: >
            New comment by {{ state_attr('sensor.kadermanager_teamname', 'events')[0].comments[0].author }}:
            {{ state_attr('sensor.kadermanager_teamname', 'events')[0].comments[0].text }}
```
</details>

<details>
<summary><b>🏟️ Announcement: Game Day!</b></summary>

Send a morning briefing if a game is scheduled for today.

```yaml
automation:
  - alias: "Kadermanager - Game Day"
    trigger:
      - platform: time
        at: "08:00:00"
    condition:
      - condition: template
        value_template: "{{ state_attr('sensor.kadermanager_teamname', 'events') }}"
      - condition: template
        value_template: "{{ state_attr('sensor.kadermanager_teamname', 'events')[0].date == now().strftime('%Y-%m-%d') }}"
      - condition: template
        value_template: "{{ state_attr('sensor.kadermanager_teamname', 'events')[0].type == 'Spiel' }}"
    action:
      - service: notify.notify
        data:
          title: "Matchday!"
          message: "Ready for the game against {{ state_attr('sensor.kadermanager_teamname', 'events')[0].title }} today at {{ state_attr('sensor.kadermanager_teamname', 'events')[0].time }}?"
```
</details>

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
