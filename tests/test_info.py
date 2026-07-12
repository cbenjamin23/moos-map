from __future__ import annotations

from pathlib import Path

import pytest

from moos_map.errors import ValidationError
from moos_map.models import Bounds, Origin
from moos_map.moos_files import parse_info_file, write_info_file


def test_info_writer_emits_only_six_active_moos_keys(tmp_path: Path) -> None:
    path = tmp_path / "harbor.info"
    bounds = Bounds(west=-71.1, south=42.3, east=-71.0, north=42.4)
    origin = Origin(latitude=42.35, longitude=-71.05)

    write_info_file(
        path,
        actual_bounds=bounds,
        origin=origin,
        source_id="test",
        source_attribution="Test Provider",
        zoom=16,
        requested_bounds=bounds,
        generator_version="test",
    )

    active = [
        line
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    ]
    assert len(active) == 6
    parsed = parse_info_file(path)
    assert parsed.bounds == bounds
    assert parsed.origin == origin
    assert any(comment.startswith("source = test") for comment in parsed.comments)
    assert "attribution = Test Provider" in parsed.comments


def test_info_parser_rejects_unknown_active_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.info"
    path.write_text(
        "lat_north=1\nlat_south=0\nlon_east=1\nlon_west=0\n"
        "datum_lat=.5\ndatum_lon=.5\nprovider=bad\n"
    )

    with pytest.raises(ValidationError, match="Unsupported .info key"):
        parse_info_file(path)


def test_info_parser_rejects_duplicate_key(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.info"
    path.write_text(
        "lat_north=1\nlat_north=2\nlat_south=0\nlon_east=1\n"
        "lon_west=0\ndatum_lat=.5\ndatum_lon=.5\n"
    )

    with pytest.raises(ValidationError, match="Duplicate .info key"):
        parse_info_file(path)
