from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from conftest import make_tile
from moos_map.errors import SourcePolicyError, ValidationError
from moos_map.models import Bounds, MapRequest, Origin, TileRange
from moos_map.geometry import bounds_for_tile_range
from moos_map.moos_files import parse_info_file
from moos_map.service import build_map, plan_map


class FakeProvider:
    def __init__(self) -> None:
        self.cache_hits = 0
        self.downloaded_tiles = 0
        self.closed = False
        self.force_values: list[bool] = []

    def fetch(self, zoom: int, x: int, y: int, *, force: bool = False) -> bytes:
        del zoom
        self.force_values.append(force)
        self.downloaded_tiles += 1
        colors = {
            (19826, 24239): (255, 0, 0),
            (19827, 24239): (0, 255, 0),
            (19826, 24240): (0, 0, 255),
            (19827, 24240): (255, 255, 0),
        }
        return make_tile(colors[(x, y)])

    def close(self) -> None:
        self.closed = True


def local_request(tmp_path: Path, **overrides: object) -> MapRequest:
    tile_bounds = bounds_for_tile_range(
        TileRange(zoom=16, x_min=19826, x_max=19827, y_min=24239, y_max=24240)
    )
    values: dict[str, object] = {
        "bounds": tile_bounds,
        "origin": Origin(latitude=42.36, longitude=-71.087),
        "zoom": 16,
        "source_id": "google-satellite",
        "name": "harbor",
        "output_dir": tmp_path,
        "emit_moos": True,
    }
    values.update(overrides)
    return MapRequest(**values)  # type: ignore[arg-type]


def test_build_creates_one_tile_aligned_moos_bundle(tmp_path: Path) -> None:
    provider = FakeProvider()

    result = build_map(local_request(tmp_path), provider=provider)

    assert result.tiff_path == tmp_path / "harbor.tif"
    assert result.info_path == tmp_path / "harbor.info"
    assert result.moos_path == tmp_path / "harbor.moos"
    assert not (tmp_path / "harbor.json").exists()
    assert result.verification["ok"] is True
    assert result.plan.pixel_width == 512
    assert result.plan.pixel_height == 512
    assert provider.downloaded_tiles == 4

    with Image.open(result.tiff_path) as image:
        assert image.format == "TIFF"
        assert image.mode == "RGB"
        assert image.getpixel((10, 10)) == (255, 0, 0)
        assert image.getpixel((300, 10)) == (0, 255, 0)
        assert image.getpixel((10, 300)) == (0, 0, 255)
        assert image.getpixel((300, 300)) == (255, 255, 0)

    info = parse_info_file(result.info_path)
    assert info.bounds.west == pytest.approx(result.plan.actual_bounds.west, abs=1e-10)
    assert info.bounds.south == pytest.approx(
        result.plan.actual_bounds.south, abs=1e-10
    )
    assert info.bounds.east == pytest.approx(result.plan.actual_bounds.east, abs=1e-10)
    assert info.bounds.north == pytest.approx(
        result.plan.actual_bounds.north, abs=1e-10
    )
    assert info.origin == Origin(latitude=42.36, longitude=-71.087)


def test_existing_output_is_replaced_by_default(tmp_path: Path) -> None:
    request = local_request(tmp_path)
    build_map(request, provider=FakeProvider())
    replacement = FakeProvider()

    result = build_map(request, provider=replacement)

    assert result.verification["ok"] is True
    assert replacement.downloaded_tiles == 4


def test_existing_output_can_be_protected(tmp_path: Path) -> None:
    build_map(local_request(tmp_path), provider=FakeProvider())

    with pytest.raises(ValidationError, match="Output protection is enabled"):
        build_map(local_request(tmp_path, overwrite=False), provider=FakeProvider())


def test_failed_force_build_preserves_existing_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = local_request(tmp_path)
    original = build_map(request, provider=FakeProvider())
    original_tiff = original.tiff_path.read_bytes()
    original_info = original.info_path.read_bytes()

    def fail_info_write(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("simulated staging failure")

    monkeypatch.setattr("moos_map.service.write_info_file", fail_info_write)
    forced = local_request(tmp_path, force=True)

    with pytest.raises(RuntimeError, match="simulated staging failure"):
        build_map(forced, provider=FakeProvider())

    assert original.tiff_path.read_bytes() == original_tiff
    assert original.info_path.read_bytes() == original_info


def test_default_overwrite_does_not_refresh_tiles(tmp_path: Path) -> None:
    build_map(local_request(tmp_path), provider=FakeProvider())

    overwrite_provider = FakeProvider()
    build_map(local_request(tmp_path), provider=overwrite_provider)
    assert overwrite_provider.force_values
    assert not any(overwrite_provider.force_values)

    refresh_provider = FakeProvider()
    build_map(
        local_request(tmp_path, name="fresh_tiles", refresh_tiles=True),
        provider=refresh_provider,
    )
    assert refresh_provider.force_values
    assert all(refresh_provider.force_values)


def test_preview_only_source_cannot_build(tmp_path: Path) -> None:
    request = local_request(
        tmp_path,
        source_id="custom",
        custom_url_template="https://example.test/{z}/{x}/{y}.png",
    )

    with pytest.raises(SourcePolicyError, match="preview-only"):
        build_map(request, provider=FakeProvider())


def test_build_crops_to_exact_requested_bounds(tmp_path: Path) -> None:
    requested = Bounds(west=-71.088, south=42.358, east=-71.087, north=42.359)
    request = local_request(
        tmp_path,
        bounds=requested,
        origin=Origin(latitude=42.3585, longitude=-71.0875),
        name="exact_crop",
        emit_moos=False,
    )

    result = build_map(request, provider=FakeProvider())

    assert result.plan.actual_bounds == requested
    assert result.plan.download_bounds != requested
    assert result.plan.pixel_width < 512
    assert result.plan.pixel_height < 512
    with Image.open(result.tiff_path) as image:
        assert image.size == (result.plan.pixel_width, result.plan.pixel_height)
    info = parse_info_file(result.info_path)
    assert info.bounds.west == pytest.approx(requested.west, abs=1e-10)
    assert info.bounds.south == pytest.approx(requested.south, abs=1e-10)
    assert info.bounds.east == pytest.approx(requested.east, abs=1e-10)
    assert info.bounds.north == pytest.approx(requested.north, abs=1e-10)


def test_outside_origin_is_allowed_with_warning(tmp_path: Path) -> None:
    request = local_request(
        tmp_path,
        origin=Origin(latitude=42.37, longitude=-71.087),
    )

    plan = plan_map(request)

    assert any("origin lies outside" in warning for warning in plan.warnings)


def test_cross_zone_map_is_rejected(tmp_path: Path) -> None:
    request = local_request(
        tmp_path,
        bounds=Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1),
        origin=Origin(latitude=42.05, longitude=-72.0),
    )

    with pytest.raises(ValidationError, match="UTM zone"):
        plan_map(request)


def test_origin_in_different_utm_zone_is_rejected(tmp_path: Path) -> None:
    request = local_request(
        tmp_path,
        origin=Origin(latitude=42.36, longitude=-72.1),
    )

    with pytest.raises(ValidationError, match="origin is in UTM zone"):
        plan_map(request)
