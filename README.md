# Kadermanager Homeassistant Integration
The `kadermanager` sensor will give informations about events and participants

<img src="https://assets1.nimenhuuto.com/assets/logos/kadermanager.de/logo_h128-9f99c175236041ce4e42e770ed364faad6945c046539b14d1828720df6baa426.png" alt="Kadermanager" width="300px">

## Installation
### 1. Using HACS (recommended way)

Not available in HACS yet, but it is planned.

### 2. Manual

- Download the latest zip release from [here](https://github.com/FaserF/ha-kadermanager/releases/latest)
- Extract the zip file
- Copy the folder "kadermanager" from within custom_components with all of its components to `<config>/custom_components/`

where `<config>` is your Home Assistant configuration directory.

>__NOTE__: Do not download the file by using the link above directly, the status in the "master" branch can be in development and therefore is maybe not working.

## Configuration

Go to Configuration -> Integrations and click on "add integration". Then search for "Kadermanager".

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kadermanager)

### Configuration Variables
- **team name**: input your kadermanager teamname (it usually is your kadermanager subdomain, f.e.: teamname.kadermanager.de)

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
Thanks for Kadermanager for their great free software!

The data is coming from the [kadermanager.de](https://kadermanager.de/) website.
