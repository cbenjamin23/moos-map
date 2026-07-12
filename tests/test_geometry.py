from __future__ import annotations

import pytest

from moos_map.geometry import (
    bounds_for_tile_range,
    crosses_utm_zone,
    estimate_vertical_mapping_error,
    tile_range_for_bounds,
)
from moos_map.models import Bounds, TileRange


def test_tile_aligned_bounds_round_trip_without_extra_row_or_column() -> None:
    expected = TileRange(zoom=16, x_min=19826, x_max=19827, y_min=24239, y_max=24240)
    bounds = bounds_for_tile_range(expected)

    assert tile_range_for_bounds(bounds, 16) == expected


def test_small_request_rounds_outward_to_every_intersecting_tile() -> None:
    request = Bounds(west=-71.088, south=42.358, east=-71.087, north=42.359)
    tiles = tile_range_for_bounds(request, 16)
    actual = bounds_for_tile_range(tiles)

    assert tiles.count == 4
    assert actual.west <= request.west
    assert actual.south <= request.south
    assert actual.east >= request.east
    assert actual.north >= request.north


def test_utm_zone_boundary_detection() -> None:
    assert crosses_utm_zone(Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1))
    assert not crosses_utm_zone(Bounds(west=-71.2, south=42.0, east=-71.0, north=42.1))


def test_vertical_mapping_error_is_small_but_nonzero_for_local_map() -> None:
    tiles = TileRange(zoom=16, x_min=19826, x_max=19827, y_min=24239, y_max=24240)

    error = estimate_vertical_mapping_error(tiles)

    assert 0 < error < 0.1


def test_invalid_bounds_are_rejected() -> None:
    with pytest.raises(Exception, match="West must be less"):
        Bounds(west=1, south=0, east=0, north=1)
