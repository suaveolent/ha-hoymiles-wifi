# Hoymiles for Home Assistant

This custom component integrates Hoymiles DTUs, HMS-XXXXW microinverters and and hybrid inverters into Home Assistant, providing live inverter data.
It uses the [hoymiles-wifi](https://github.com/suaveolent/hoymiles-wifi) Python library to communicate directly with the devices over your local network — no cloud connection required.

> [!NOTE]
> Disclaimer: This library is not affiliated with Hoymiles. It is an independent project developed to provide tools for interacting with Hoymiles DTUs and Hoymiles HMS-XXXXW series micro-inverters featuring integrated WiFi DTU. Any trademarks or product names mentioned are the property of their respective owners.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/suaveolent)

## Supported Devices

The custom component was successfully tested with:

- Hoymiles HMS-400W-1T
- Hoymiles HMS-800W-2T
- Hoymiles HMS-1000W-2T
- Hoymiles HMS-2000DW-4T
- Hoymiles DTU-WLite
- Hoymiles DTU-Pro (S)
- Hoymiles HAS-5.0LV-EUG1
- Hoymiles HYS-4.6LV-EUG1
- Hoymiles HYT-5.0HV-EUG1
- Solenso H-1000 (not tested for command, only to get data)
- Solenso DTU_SLS (not tested for command, only to get data)

## Warning

> [!CAUTION]
> Please refrain from using the current power limitation feature for zero feed-in, as it may lead to damaging the inverter due to excessive writes to the EEPROM.

## Installation

1. Open the [HACS](https://hacs.xyz) panel in your Home Assistant frontend.

2. Navigate to the "Integrations" tab.

3. Click the three dots in the top-right corner and select "Custom Repositories."

4. Add a new custom repository:

- **URL:** `https://github.com/suaveolent/ha-hoymiles-wifi`

- **Category:** Integration

5. Click "Add"

6. Click on the `Hoymiles` integration.

7. Click "DOWNLOAD"

8. Navigate to "Settings" - "Devices & Services"

9. Click "ADD INTEGRATION" and select the `Hoymiles` integration.

10. Insert IP address of hoymiles DTUBI-xxxx in field Host and click on SUBMIT

> [!NOTE]
> Sometimes the necessary lib
> (https://github.com/suaveolent/hoymiles-wifi) is not correctly
> installed. In this case you need to manually install the library by
> running the `pip install hoymiles-wifi` command yourself.

### Option 2: Manual Installation

1. Download the contents of this repository as a ZIP file.

2. Extract the ZIP file.

3. Copy the entire `custom_components/hoymiles-wifi` directory to your Home Assistant

4. Install the python requirements

5. Restart your Home Assistant instance to apply the changes.

### Docker Users: Workaround for HTTP 500 Error

If you encounter an HTTP 500 error when adding the integration in a Home Assistant Docker container, follow this workaround:

1. Create a new Docker image for Home Assistant with the `hoymiles-wifi` library pre-installed:
   ```dockerfile
   FROM homeassistant/home-assistant
   RUN pip install hoymiles-wifi
   ```
2. Build the new Docker image:
   ```bash
   docker build -t ha-hoymiles .
   ```
3. Switch to this newly built image when running Home Assistant.

## Configuration

Configuration is done in the UI.

1. `Host`: Enter the IP address or the hostname of your inverter or DTU.

> [!NOTE]
> To find the IP address or hostname of your inverter/DTU, you can either access your router’s web interface to view connected devices, or use a network scanning tool (such as Fing or Angry IP Scanner) to identify the device on your local network.

2. `Update interval (seconds)`: This defines how frequently the system will request data from the inverter or DTU. Enter the desired time in seconds.

> [!NOTE]
> Setting the update interval below approximately 32 seconds may disable Hoymiles cloud functionality. To ensure proper communication with Hoymiles servers, keep the update interval at or above this threshold.

## Screenshots

![Integration](/screenshots/integration.png?raw=true)
![Devices](/screenshots/devices.png?raw=true)
![Device](/screenshots/device.png?raw=true)

## Caution

Use this custom component responsibly and be aware of potential risks. There are no guarantees provided, and any misuse or incorrect implementation may result in undesirable outcomes. Ensure that your inverter is not compromised during communication.

## Known Limitations

> [!NOTE]
> **Update Frequency:** The library may experience limitations in fetching updates, potentially around twice per minute. The inverter firmware may enforce a mandatory wait period of approximately 30 seconds between requests.
> This issue can be identified when the data returned matches the response from the previous request.
> If you encounter this, you can try the _experimental_ performance data mode. (Needs to be enabled on each reboot of the DTU.)

> [!NOTE]
> **Compatibility:** While developed for the HMS-800W-2T inverter, compatibility with other inverters from the series is untested at the time of writing. Exercise caution and conduct thorough testing if using with different inverter models.

## Attribution

This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.
