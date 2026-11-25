from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from moos_map.cli import build_parser, run
from moos_map.models import Bounds, Origin
from moos_map.moos_files import write_info_file, write_moos_snippet
from moos_map.verification import verify_bundle


def write_bundle(tmp_path: Path, bounds: Bounds, origin: Origin) -> Path:
    tiff_path = tmp_path / "cross_zone.tif"
    Image.new("RGB", (16, 16)).save(tiff_path, format="TIFF")
    write_info_file(
        tiff_path.with_suffix(".info"),
        actual_bounds=bounds,
        origin=origin,
        source_id="test",
        source_attribution="Test Provider",
        zoom=16,
        requested_bounds=bounds,
        generator_version="test",
    )
    return tiff_path


def test_cross_zone_bundle_is_valid_with_current_proj_geodesy(tmp_path: Path) -> None:
    tiff_path = write_bundle(
        tmp_path,
        Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1),
        Origin(latitude=42.05, longitude=-72.0),
    )

    report = verify_bundle(tiff_path)

    assert report.ok
    assert report.warnings == ()
    assert report.details["pmarineviewer_estimate"]["width_m"] > 16_000


def test_different_map_and_origin_zones_are_valid(tmp_path: Path) -> None:
    tiff_path = write_bundle(
        tmp_path,
        Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1),
        Origin(latitude=42.05, longitude=-72.05),
    )

    report = verify_bundle(tiff_path)

    assert report.ok
    assert report.warnings == ()
    assert report.details["pmarineviewer_estimate"][
        "estimated_max_position_error_m"
    ] > 800


def test_equator_crossing_bundle_uses_datum_hemisphere(tmp_path: Path) -> None:
    tiff_path = write_bundle(
        tmp_path,
        Bounds(west=-3.005, south=-0.005, east=-2.995, north=0.005),
        Origin(latitude=0.0, longitude=-3.0),
    )

    report = verify_bundle(tiff_path)

    assert report.ok
    assert report.warnings == ()
    assert report.details["pmarineviewer_estimate"]["height_m"] == pytest.approx(
        1_105.300465,
        abs=0.001,
    )
    assert report.details["pmarineviewer_estimate"][
        "estimated_max_position_error_m"
    ] < 0.001


def test_verify_json_reports_invalid_info_encoding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tiff_path = write_bundle(
        tmp_path,
        Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1),
        Origin(latitude=42.05, longitude=-72.0),
    )
    tiff_path.with_suffix(".info").write_bytes(b"// damaged metadata\xff\n")

    assert run(build_parser().parse_args(["verify", str(tiff_path), "--json"])) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["ok"] is False
    assert any("UTF-8" in error for error in report["errors"])
    assert captured.err == ""


@pytest.mark.parametrize("kind", ["matching", "stale", "custom"])
def test_verify_warns_for_a_stale_generated_mission_snippet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    origin = Origin(latitude=42.05, longitude=-72.0)
    tiff_path = write_bundle(
        tmp_path, Bounds(west=-72.1, south=42, east=-71.9, north=42.1), origin
    )
    snippet = tiff_path.with_suffix(".moos")
    if kind == "custom":
        snippet.write_text("LatOrigin = 0\nLongOrigin = 0\ntiff_file = other.tif\n", encoding="utf-8")
    else:
        write_moos_snippet(
            snippet, tiff_name=tiff_path.name if kind == "matching" else "other.tif",
            origin=origin if kind == "matching" else Origin(latitude=42.04, longitude=-72.05),
        )

    assert run(build_parser().parse_args(["verify", str(tiff_path), "--json"])) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"]
    if kind == "stale":
        assert "LatOrigin, LongOrigin, tiff_file" in report["warnings"][0]
    else:
        assert not report["warnings"]
