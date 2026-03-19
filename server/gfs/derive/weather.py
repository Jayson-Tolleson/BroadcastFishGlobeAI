from __future__ import annotations

from typing import Any


def derive_weather_fields(raw: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "wind_u": raw.get("wind_u", raw.get("u-component_of_wind_height_above_ground", [])),
        "wind_v": raw.get("wind_v", raw.get("v-component_of_wind_height_above_ground", [])),
        "gust": raw.get("wind_gust", raw.get("Wind_speed_gust_surface", [])),
        "pressure_msl": raw.get("pressure_msl", raw.get("Pressure_reduced_to_MSL_msl", [])),
        "air_temp": raw.get("air_temp", raw.get("Temperature_height_above_ground", [])),
        "dewpoint": raw.get("dewpoint", raw.get("Dewpoint_temperature_height_above_ground", [])),
        "precip_rate": raw.get("precip_rate", raw.get("Precipitation_rate_surface", [])),
        "cloud_total": raw.get("cloud_total", raw.get("Total_cloud_cover_entire_atmosphere", [])),
        "rel_humidity": raw.get("rel_humidity", raw.get("Relative_humidity_height_above_ground", [])),
    }
    fields.update({
        "mslp": fields["pressure_msl"],
        "temp2m": fields["air_temp"],
        "dewpoint2m": fields["dewpoint"],
        "prate": fields["precip_rate"],
        "cloud_cover": fields["cloud_total"],
    })
    return fields
