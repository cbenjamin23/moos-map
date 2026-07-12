from __future__ import annotations

import math

from .errors import ValidationError
from .models import Bounds, TileRange, WEB_MERCATOR_MAX_LAT


EARTH_RADIUS_M = 6_378_137.0
EARTH_CIRCUMFERENCE_M = 2 * math.pi * EARTH_RADIUS_M


def _validate_zoom(zoom: int) -> None:
    if not isinstance(zoom, int) or not 0 <= zoom <= 30:
        raise ValidationError("Zoom must be an integer between 0 and 30")


def longitude_to_tile_x(longitude: float, zoom: int) -> float:
    _validate_zoom(zoom)
    return (longitude + 180.0) / 360.0 * (1 << zoom)


def latitude_to_tile_y(latitude: float, zoom: int) -> float:
    _validate_zoom(zoom)
    latitude = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, latitude))
    latitude_radians = math.radians(latitude)
    return (1.0 - math.asinh(math.tan(latitude_radians)) / math.pi) / 2.0 * (1 << zoom)


def tile_x_to_longitude(x: float, zoom: int) -> float:
    _validate_zoom(zoom)
    return x / (1 << zoom) * 360.0 - 180.0


def tile_y_to_latitude(y: float, zoom: int) -> float:
    _validate_zoom(zoom)
    mercator = math.pi * (1.0 - 2.0 * y / (1 << zoom))
    return math.degrees(math.atan(math.sinh(mercator)))


def tile_range_for_bounds(bounds: Bounds, zoom: int) -> TileRange:
    """Return the minimal inclusive XYZ tile range intersecting the bounds.

    The east and south sides are treated as exclusive. This avoids adding an
    unnecessary column or row when a requested edge lies exactly on a tile
    boundary.
    """

    _validate_zoom(zoom)
    limit = (1 << zoom) - 1

    west_x = longitude_to_tile_x(bounds.west, zoom)
    east_x = longitude_to_tile_x(bounds.east, zoom)
    north_y = latitude_to_tile_y(bounds.north, zoom)
    south_y = latitude_to_tile_y(bounds.south, zoom)

    x_min = max(0, min(limit, math.floor(west_x)))
    x_max = max(0, min(limit, math.ceil(east_x) - 1))
    y_min = max(0, min(limit, math.floor(north_y)))
    y_max = max(0, min(limit, math.ceil(south_y) - 1))

    if x_max < x_min or y_max < y_min:
        raise ValidationError("Bounds do not intersect a valid XYZ tile")

    return TileRange(
        zoom=zoom,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
    )


def bounds_for_tile_range(tiles: TileRange) -> Bounds:
    return Bounds(
        west=tile_x_to_longitude(tiles.x_min, tiles.zoom),
        south=tile_y_to_latitude(tiles.y_max + 1, tiles.zoom),
        east=tile_x_to_longitude(tiles.x_max + 1, tiles.zoom),
        north=tile_y_to_latitude(tiles.y_min, tiles.zoom),
    )


def meters_per_pixel(latitude: float, zoom: int, tile_size: int = 256) -> float:
    _validate_zoom(zoom)
    return (
        EARTH_CIRCUMFERENCE_M
        * math.cos(math.radians(latitude))
        / ((1 << zoom) * tile_size)
    )


def approximate_ground_size(bounds: Bounds) -> tuple[float, float]:
    center_latitude = (bounds.north + bounds.south) / 2.0
    width = (
        math.radians(bounds.east - bounds.west)
        * EARTH_RADIUS_M
        * math.cos(math.radians(center_latitude))
    )
    height = math.radians(bounds.north - bounds.south) * EARTH_RADIUS_M
    return abs(width), abs(height)


def estimate_vertical_mapping_error(tiles: TileRange, samples: int = 256) -> float:
    """Estimate Web Mercator-vs-affine northing error across a raster.

    XYZ tile rows are linear in Web Mercator Y. pMarineViewer stretches the
    raster linearly between its north and south geographic edges. The two
    agree at the edges but diverge slightly between them.
    """

    if samples < 2:
        raise ValidationError("Mapping error estimate requires at least two samples")
    north = tile_y_to_latitude(tiles.y_min, tiles.zoom)
    south = tile_y_to_latitude(tiles.y_max + 1, tiles.zoom)
    span = tiles.rows
    maximum_error = 0.0
    for index in range(1, samples):
        fraction = index / samples
        mercator_latitude = tile_y_to_latitude(
            tiles.y_min + fraction * span, tiles.zoom
        )
        affine_latitude = north + fraction * (south - north)
        error_m = (
            abs(math.radians(mercator_latitude - affine_latitude)) * EARTH_RADIUS_M
        )
        maximum_error = max(maximum_error, error_m)
    return maximum_error


def utm_zone_number(longitude: float, latitude: float | None = None) -> int:
    """Return the UTM zone, including MOOSGeodesy's Norway/Svalbard rules."""

    if longitude == 180:
        return 60
    zone = int((longitude + 180) // 6) + 1
    if latitude is not None and 56 <= latitude < 64 and 3 <= longitude < 12:
        return 32
    if latitude is not None and 72 <= latitude < 84:
        if 0 <= longitude < 9:
            return 31
        if 9 <= longitude < 21:
            return 33
        if 21 <= longitude < 33:
            return 35
        if 33 <= longitude < 42:
            return 37
    return zone


def crosses_utm_zone(bounds: Bounds) -> bool:
    epsilon = 1e-12
    corners = {
        utm_zone_number(bounds.west, bounds.south),
        utm_zone_number(bounds.west, bounds.north),
        utm_zone_number(bounds.east - epsilon, bounds.south),
        utm_zone_number(bounds.east - epsilon, bounds.north),
    }
    return len(corners) != 1
