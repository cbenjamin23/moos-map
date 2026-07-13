from __future__ import annotations

import pytest

from moos_map.errors import ValidationError
from moos_map.sources import BUILTIN_SOURCES, resolve_source


def test_high_detail_ray_and_anaxi_sources_are_built_in() -> None:
    google = resolve_source("google-satellite")
    hybrid = resolve_source("google-hybrid")
    esri = resolve_source("esri-world-imagery")

    assert google.max_zoom == 22
    assert hybrid.max_zoom == 22
    assert esri.max_zoom == 21
    assert google.export_allowed is True
    assert esri.export_allowed is True
    assert {
        "google-maps",
        "google-terrain-hybrid",
        "esri-world-street",
        "esri-world-topo",
        "esri-ocean",
    }.issubset(BUILTIN_SOURCES)
    assert "usgs-imagery" not in BUILTIN_SOURCES
    assert "usgs-topo" not in BUILTIN_SOURCES
    assert "osm-preview" not in BUILTIN_SOURCES


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
