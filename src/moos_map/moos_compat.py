from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import latitude_to_tile_y, tile_y_to_latitude, utm_zone_number
from .models import Bounds, Origin


# Values used by CMOOSGeodesy for reference ellipsoid 23 (WGS-84).
WGS84_SEMI_MAJOR_AXIS_M = 6_378_137.0
MOOS_WGS84_ECCENTRICITY_SQUARED = 0.00669438
UTM_SCALE_FACTOR = 0.9996


@dataclass(frozen=True, slots=True)
class PMarineViewerEstimate:
    width_m: float
    height_m: float
    image_center_x_m: float
    image_center_y_m: float
    max_position_error_m: float
    requested_area_max_position_error_m: float


def moos_utm(latitude: float, longitude: float) -> tuple[float, float]:
    """Replicate the WGS-84 LLtoUTM calculation in CMOOSGeodesy.

    Returns (northing, easting). CMOOSGeodesy independently chooses a zone
    for every point, which is why moos-map rejects zone-crossing rasters.
    """

    long_temp = (longitude + 180.0) % 360.0 - 180.0
    latitude_radians = math.radians(latitude)
    longitude_radians = math.radians(long_temp)
    zone = utm_zone_number(long_temp, latitude)
    central_longitude = (zone - 1) * 6 - 180 + 3
    central_longitude_radians = math.radians(central_longitude)

    eccentricity_squared = MOOS_WGS84_ECCENTRICITY_SQUARED
    eccentricity_prime_squared = eccentricity_squared / (1 - eccentricity_squared)
    sin_latitude = math.sin(latitude_radians)
    cos_latitude = math.cos(latitude_radians)
    tangent = math.tan(latitude_radians)
    n = WGS84_SEMI_MAJOR_AXIS_M / math.sqrt(
        1 - eccentricity_squared * sin_latitude * sin_latitude
    )
    t = tangent * tangent
    c = eccentricity_prime_squared * cos_latitude * cos_latitude
    a = cos_latitude * (longitude_radians - central_longitude_radians)

    meridional_arc = WGS84_SEMI_MAJOR_AXIS_M * (
        (
            1
            - eccentricity_squared / 4
            - 3 * eccentricity_squared**2 / 64
            - 5 * eccentricity_squared**3 / 256
        )
        * latitude_radians
        - (
            3 * eccentricity_squared / 8
            + 3 * eccentricity_squared**2 / 32
            + 45 * eccentricity_squared**3 / 1024
        )
        * math.sin(2 * latitude_radians)
        + (15 * eccentricity_squared**2 / 256 + 45 * eccentricity_squared**3 / 1024)
        * math.sin(4 * latitude_radians)
        - (35 * eccentricity_squared**3 / 3072) * math.sin(6 * latitude_radians)
    )

    easting = (
        UTM_SCALE_FACTOR
        * n
        * (
            a
            + (1 - t + c) * a**3 / 6
            + (5 - 18 * t + t**2 + 72 * c - 58 * eccentricity_prime_squared)
            * a**5
            / 120
        )
        + 500_000.0
    )
    northing = UTM_SCALE_FACTOR * (
        meridional_arc
        + n
        * tangent
        * (
            a**2 / 2
            + (5 - t + 9 * c + 4 * c**2) * a**4 / 24
            + (61 - 58 * t + t**2 + 600 * c - 330 * eccentricity_prime_squared)
            * a**6
            / 720
        )
    )
    if latitude < 0:
        northing += 10_000_000.0
    return northing, easting


def estimate_pmarineviewer_placement(
    bounds: Bounds,
    origin: Origin,
    *,
    requested_bounds: Bounds | None = None,
    samples_per_axis: int = 12,
) -> PMarineViewerEstimate:
    """Predict the default UTM BackImg rectangle and its worst sampled error."""

    if samples_per_axis < 1:
        raise ValueError("samples_per_axis must be at least one")

    northwest_northing, northwest_easting = moos_utm(bounds.north, bounds.west)
    southeast_northing, southeast_easting = moos_utm(bounds.south, bounds.east)
    width = abs(northwest_easting - southeast_easting)
    height = abs(northwest_northing - southeast_northing)

    origin_x_fraction = (origin.longitude - bounds.west) / (bounds.east - bounds.west)
    origin_y_fraction = (origin.latitude - bounds.south) / (bounds.north - bounds.south)
    center_x = (0.5 - origin_x_fraction) * width
    center_y = (0.5 - origin_y_fraction) * height

    origin_northing, origin_easting = moos_utm(origin.latitude, origin.longitude)
    image_north_y = latitude_to_tile_y(bounds.north, 0)
    image_south_y = latitude_to_tile_y(bounds.south, 0)

    def sampled_maximum(sample_bounds: Bounds) -> float:
        sample_north_y = latitude_to_tile_y(sample_bounds.north, 0)
        sample_south_y = latitude_to_tile_y(sample_bounds.south, 0)
        maximum = 0.0
        for vertical_index in range(samples_per_axis + 1):
            sample_v = vertical_index / samples_per_axis
            mercator_y = sample_north_y + sample_v * (sample_south_y - sample_north_y)
            latitude = tile_y_to_latitude(mercator_y, 0)
            image_v = (mercator_y - image_north_y) / (image_south_y - image_north_y)
            displayed_y = (1.0 - origin_y_fraction - image_v) * height
            for horizontal_index in range(samples_per_axis + 1):
                sample_u = horizontal_index / samples_per_axis
                longitude = sample_bounds.west + sample_u * (
                    sample_bounds.east - sample_bounds.west
                )
                image_u = (longitude - bounds.west) / (bounds.east - bounds.west)
                displayed_x = (image_u - origin_x_fraction) * width
                northing, easting = moos_utm(latitude, longitude)
                true_x = easting - origin_easting
                true_y = northing - origin_northing
                maximum = max(
                    maximum,
                    math.hypot(displayed_x - true_x, displayed_y - true_y),
                )
        return maximum

    maximum_error = sampled_maximum(bounds)
    requested_error = sampled_maximum(requested_bounds or bounds)

    return PMarineViewerEstimate(
        width_m=width,
        height_m=height,
        image_center_x_m=center_x,
        image_center_y_m=center_y,
        max_position_error_m=maximum_error,
        requested_area_max_position_error_m=requested_error,
    )
