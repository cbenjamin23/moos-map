from __future__ import annotations

import pytest

from moos_map.models import Bounds, Origin
from moos_map.moos_compat import estimate_pmarineviewer_placement


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
