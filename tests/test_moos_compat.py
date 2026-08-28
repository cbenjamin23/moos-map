from __future__ import annotations

import pytest

from moos_map.models import Bounds, Origin
from moos_map.moos_compat import estimate_pmarineviewer_placement, moos_utm


def test_fixed_zone_projection_remains_continuous_across_boundary() -> None:
    _, west_easting = moos_utm(0.0, -0.0001, zone=30)
    _, east_easting = moos_utm(0.0, 0.0001, zone=30)

    assert east_easting - west_easting == pytest.approx(22.28574, abs=0.001)


def test_fixed_hemisphere_projection_remains_continuous_across_equator() -> None:
    north_northing, _ = moos_utm(
        0.0001,
        -3.0,
        zone=30,
        southern_hemisphere=False,
    )
    south_northing, _ = moos_utm(
        -0.0001,
        -3.0,
        zone=30,
        southern_hemisphere=False,
    )
    southern_frame_northing, _ = moos_utm(
        0.0001,
        -3.0,
        zone=30,
        southern_hemisphere=True,
    )
    natural_south_northing, _ = moos_utm(-0.0001, -3.0, zone=30)

    assert north_northing > 0 > south_northing
    assert north_northing - south_northing == pytest.approx(22.106, abs=0.001)
    assert southern_frame_northing - north_northing == pytest.approx(10_000_000)
    assert natural_south_northing - south_northing == pytest.approx(10_000_000)


def test_estimate_matches_current_backimg_probe() -> None:
    bounds = Bounds(
        west=-71.092529296875,
        south=42.35448465106745,
        east=-71.08154296875,
        north=42.36260292171997,
    )

    estimate = estimate_pmarineviewer_placement(
        bounds,
        Origin(latitude=42.3585, longitude=-71.0875),
        requested_bounds=Bounds(
            west=-71.088,
            south=42.358,
            east=-71.087,
            north=42.359,
        ),
    )

    # Current BackImg probe reports integer-truncated 882x923 and center
    # (37.2678, 4.98198) for this exact generated bundle.
    assert estimate.width_m == pytest.approx(882.6581, abs=0.001)
    assert estimate.height_m == pytest.approx(923.6906, abs=0.001)
    assert estimate.image_center_x_m == pytest.approx(37.2678, abs=0.001)
    assert estimate.image_center_y_m == pytest.approx(4.9820, abs=0.001)
    assert estimate.requested_area_max_position_error_m < estimate.max_position_error_m


def test_estimate_uses_map_center_zone_across_utm_boundary() -> None:
    estimate = estimate_pmarineviewer_placement(
        Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1),
        Origin(latitude=42.05, longitude=-72.0),
    )

    assert estimate.width_m == pytest.approx(16_163.118, abs=0.01)
    assert estimate.height_m == pytest.approx(11_685.607, abs=0.01)
    assert estimate.max_position_error_m == pytest.approx(707.274, abs=0.1)


@pytest.mark.parametrize(
    ("bounds", "origin", "expected_height_m"),
    [
        (
            Bounds(west=-3.005, south=-0.005, east=-2.995, north=0.005),
            Origin(latitude=0.0, longitude=-3.0),
            1_105.300465,
        ),
        (
            Bounds(west=-3.005, south=-0.01, east=-2.995, north=0.005),
            Origin(latitude=-0.0025, longitude=-3.0),
            1_657.950698,
        ),
    ],
)
def test_estimate_uses_datum_hemisphere_across_equator(
    bounds: Bounds,
    origin: Origin,
    expected_height_m: float,
) -> None:
    estimate = estimate_pmarineviewer_placement(bounds, origin)

    assert estimate.height_m == pytest.approx(expected_height_m, abs=0.001)
    assert estimate.max_position_error_m < 0.001
