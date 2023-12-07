# from homeassistant.helpers.entity import Entity

# class PVTrackerSensor(Entity):
#     """Representation of port_state."""

#     def __init__(self):
#         """Initialize the sensor."""
#         self._state = None
#         self._pv_port = None
#         self._pv_voltage = None
#         self._pv_current = None
#         self._pv_power = None
#         self._pv_energy_total = None
#         self._pv_daily_yield = None

#     @property
#     def name(self):
#         """Return the name of the sensor."""
#         return "PV Tracker Power"

#     @property
#     def state(self):
#         """Return the state of the sensor."""
#         return self._state

#     @property
#     def unit_of_measurement(self):
#         """Return the unit of measurement."""
#         return "W"

#     @property
#     def device_state_attributes(self):
#         """Return the state attributes."""
#         return {
#             "pv_voltage": self._pv_voltage,
#             "pv_current": self._pv_current,
#             "pv_power": self._pv_power,
#             "pv_energy_total": self._pv_energy_total,
#             "pv_daily_yield": self._pv_daily_yield,
#             # Add more attributes as needed
#         }

#     def update_from_inverter(self, response):
#         """Update the tracker sensor using data from the inverter."""
#         try:
#             # Assuming response is a dictionary with the current power value
#             self._state = float(response.get("pv_current_power"))

#             # Extracting tracker-specific information
#             tracker_info = response.get("port_state", {})
#             self._pv_voltage = tracker_info.get("pv_vol")
#             self._pv_current = tracker_info.get("pv_cur")
#             self._pv_power = tracker_info.get("pv_power")
#             self._pv_energy_total = tracker_info.get("pv_energy_total")
#             self._pv_daily_yield = tracker_info.get("pv_daily_yield")
#             # Add more attribute assignments as needed
#         except Exception as error:
#             _LOGGER.error("Error updating PV tracker sensor: %s", error)
#             self._state = None
