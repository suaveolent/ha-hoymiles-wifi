# HMS-XXXXW-T2 for Home Assistant
This Home Assistant custom component utilizes the `hoymiles-wifi` Python library, allowing seamless integration with Hoymiles HMS microinverters, specifically designed for the HMS-XXXXW-T2 series. Special thanks to [DennisOSRM](https://github.com/DennisOSRM) for inspiring and contributing to the codebase through the [hms-mqtt-publisher](https://github.com/DennisOSRM/hms-mqtt-publisher) repository.

**Disclaimer: This custom component is an independent project and is not affiliated with Hoymiles. It has been developed to provide Home Assistant users with tools for interacting with Hoymiles HMS-XXXXW-T2 series micro-inverters featuring integrated WiFi DTU. Any trademarks or product names mentioned are the property of their respective owners.**


## Installation

### Option 1: HACS (Home Assistant Community Store)

1. Make sure you have [HACS](https://hacs.xyz/) installed and configured in your Home Assistant instance.
2. Open the HACS panel in your Home Assistant frontend.
3. Navigate to the "Integrations" tab.
4. Click the "+" button in the bottom right.
5. Search for "hoymiles-wifi" in the search bar.
6. Click on the search result, then click "Install."
7. Restart your Home Assistant instance to apply the changes.

### Option 2: Manual Installation

1. Download the contents of this repository as a ZIP file.
2. Extract the ZIP file.
3. Copy the entire `custom_components/hoymiles-wifi` directory to your Home Assistant
4. Install the python requirements
5. Restart your Home Assistant instance to apply the changes.

## Configuration

Configuration is done in the UI


## Caution

Use this custom component responsibly and be aware of potential risks. There are no guarantees provided, and any misuse or incorrect implementation may result in undesirable outcomes. Ensure that your inverter is not compromised during communication.

  
## Known Limitations

**Update Frequency:** The library may experience limitations in fetching updates, potentially around twice per minute. The inverter firmware may enforce a mandatory wait period of approximately 30 seconds between requests.

**Compatibility:** While developed for the HMS-800W-T2 inverter, compatibility with other inverters from the series is untested at the time of writing. Exercise caution and conduct thorough testing if using with different inverter models.
