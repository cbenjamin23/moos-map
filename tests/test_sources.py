from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from moos_map.errors import ValidationError
from moos_map.geometry import tile_range_for_bounds
from moos_map.models import Bounds, MapRequest, Origin
from moos_map.service import plan_map
from moos_map.sources import BUILTIN_SOURCES, resolve_source


def test_curated_high_detail_sources_are_built_in() -> None:
    google = resolve_source("google-satellite")
    hybrid = resolve_source("google-hybrid")
    esri = resolve_source("esri-world-imagery")

    assert google.max_zoom == 22
    assert hybrid.max_zoom == 22
    assert esri.max_zoom == 21
    assert google.export_allowed is True
    assert esri.export_allowed is True
    assert set(BUILTIN_SOURCES) == {
        "google-maps",
        "google-satellite",
        "google-hybrid",
        "esri-world-imagery",
        "esri-world-topo",
    }
    assert "usgs-imagery" not in BUILTIN_SOURCES
    assert "usgs-topo" not in BUILTIN_SOURCES
    assert "osm-preview" not in BUILTIN_SOURCES
    assert all(
        "Anaxi" not in source.note and "Ray" not in source.note
        for source in BUILTIN_SOURCES.values()
    )


def test_custom_xyz_requires_all_placeholders() -> None:
    with pytest.raises(ValidationError, match="must contain"):
        resolve_source("custom", custom_url_template="https://example/{z}/{x}.png")


def test_custom_xyz_export_requires_explicit_terms_acknowledgement() -> None:
    template = "https://example/{z}/{x}/{y}.png"

    preview = resolve_source("custom", custom_url_template=template)
    export = resolve_source(
        "custom",
        custom_url_template=template,
        accept_custom_source_terms=True,
    )

    assert preview.preview_allowed is True
    assert preview.export_allowed is False
    assert export.export_allowed is True


@pytest.mark.parametrize("bad_field", ["{s}", "{x.real}", "{y:03d}", "{"])
def test_plan_rejects_unsupported_custom_template_fields(bad_field: str) -> None:
    with pytest.raises(ValidationError, match="custom URL template"):
        resolve_source("custom", custom_url_template="https://example.test/{z}/{x}/{y}/" + bad_field)


def test_mbtiles_plan_rejects_a_gap_between_available_zooms(tmp_path: Path) -> None:
    archive = tmp_path / "sparse.mbtiles"
    bounds = Bounds(west=-71.09, south=42.35, east=-71.08, north=42.36)
    tiles = tile_range_for_bounds(bounds, 2)
    with closing(sqlite3.connect(archive)) as connection:
        connection.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
        connection.executemany(
            "INSERT INTO tiles VALUES (?, ?, ?, ?)",
            [(0, 0, 0, b"tile")] + [(2, x, 3 - y, b"tile") for x, y in tiles.coordinates()],
        )
        connection.commit()
    origin = Origin(latitude=42.355, longitude=-71.085)
    with pytest.raises(ValidationError, match="no tiles at zoom 1. Available zoom levels: 0, 2"):
        plan_map(MapRequest(bounds, origin, zoom=1, mbtiles_path=archive))
    plan = plan_map(MapRequest(bounds, origin, zoom=2, mbtiles_path=archive))
    assert plan.source["available_zooms"] == (0, 2)


def test_mbtiles_plan_rejects_incomplete_coverage_at_available_zoom(tmp_path: Path) -> None:
    archive = tmp_path / "coverage-gap.mbtiles"
    bounds = Bounds(west=103.8485, south=1.2585, east=103.852, north=1.2615)
    tiles = tile_range_for_bounds(bounds, 17)
    rows = [(17, x, (1 << 17) - 1 - y, b"tile") for x, y in tiles.coordinates()]
    with closing(sqlite3.connect(archive)) as connection:
        connection.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
        # A duplicate tile must never make up for a missing coordinate.
        connection.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", rows[:-1] + rows[:1])
        connection.commit()
        request = MapRequest(bounds, Origin(1.26, 103.85), mbtiles_path=archive)
        with pytest.raises(ValidationError, match=f"covers {tiles.count - 1} of {tiles.count} requested tiles"):
            plan_map(request)
        connection.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", rows[-1])
        connection.commit()
    assert plan_map(request).tiles.count == tiles.count
