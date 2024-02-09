# HMS-XXXXW-T2 for Home Assistant
This Home Assistant custom component utilizes the [hoymiles-wifi](https://github.com/suaveolent/hoymiles-wifi) Python library, allowing seamless integration with Hoymiles HMS microinverters, specifically designed for the HMS-XXXXW-T2 series.

**Disclaimer: This custom component is an independent project and is not affiliated with Hoymiles. It has been developed to provide Home Assistant users with tools for interacting with Hoymiles HMS-XXXXW-T2 series micro-inverters featuring integrated WiFi DTU. Any trademarks or product names mentioned are the property of their respective owners.**

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/suaveolent)


## Installation

1. Open the [HACS](https://hacs.xyz) panel in your Home Assistant frontend.
2. Navigate to the "Integrations" tab.
3. Click the three dots in the top-right corner and select "Custom Repositories."
4. Add a new custom repository:
   - **URL:** `https://github.com/suaveolent/ha-hoymiles-wifi`
   - **Category:** Integration

5. Click "Add" and then click "Install" on the `Hoymiles HMS-XXXXW-T2` integration.


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

## Attribution
This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.
