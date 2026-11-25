from __future__ import annotations

import os
from dataclasses import replace
from multiprocessing import get_context
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from conftest import make_tile
from moos_map import service
from moos_map.errors import SourcePolicyError, ValidationError
from moos_map.models import Bounds, MapRequest, Origin, TileRange
from moos_map.geometry import bounds_for_tile_range
from moos_map.moos_files import parse_info_file
from moos_map.service import build_map, plan_map
from moos_map.verification import verify_bundle


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
    }
    values.update(overrides)
    return MapRequest(**values)  # type: ignore[arg-type]


def test_build_creates_one_tile_aligned_moos_bundle(tmp_path: Path) -> None:
    provider = FakeProvider()

    result = build_map(local_request(tmp_path), provider=provider)

    assert result.tiff_path == tmp_path / "harbor" / "harbor.tif"
    assert result.info_path == tmp_path / "harbor" / "harbor.info"
    assert result.moos_path == tmp_path / "harbor" / "harbor.moos"
    assert not (tmp_path / "harbor" / "harbor.json").exists()
    assert result.verification["ok"] is True
    assert result.verification["details"]["file_size_bytes"] == (
        result.tiff_path.stat().st_size
    )
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


def test_verification_rejects_mixed_exports_even_with_the_same_bounds(tmp_path: Path) -> None:
    first = build_map(local_request(tmp_path, name="first"), provider=FakeProvider())
    second = build_map(local_request(tmp_path, name="second"), provider=FakeProvider())
    assert first.verification["ok"] and second.verification["ok"]

    original = first.info_path.read_bytes()
    first.info_path.write_bytes(second.info_path.read_bytes())
    assert not verify_bundle(first.tiff_path).ok

    first.info_path.write_bytes(original + b"// Copied to the mission folder\n")
    assert verify_bundle(first.tiff_path).ok

    first.info_path.write_bytes(original.replace(b"-71.0870000000", b"-71.0880000000"))
    assert not verify_bundle(first.tiff_path).ok


def test_existing_output_can_be_protected(tmp_path: Path) -> None:
    build_map(local_request(tmp_path), provider=FakeProvider())

    with pytest.raises(ValidationError, match="Output protection is enabled"):
        build_map(local_request(tmp_path, overwrite=False), provider=FakeProvider())


def _run_concurrent_build(request: MapRequest, before_fetch, results) -> None:
    fetch_tile_range = service.fetch_tile_range

    def fetch_after_both_preflight_checks(*args, **kwargs):
        before_fetch.wait(timeout=10)
        return fetch_tile_range(*args, **kwargs)

    with patch.object(service, "fetch_tile_range", fetch_after_both_preflight_checks):
        try:
            result = build_map(request, provider=FakeProvider())
        except ValidationError as exc:
            results.put(("error", str(exc)))
        else:
            details = result.verification["details"]
            results.put(("built", (details["origin"], details["pixel_width"], result.plan.pixel_width)))


@pytest.mark.parametrize("overwrite", [False, True])
def test_concurrent_builds_install_consistent_bundles(tmp_path: Path, overwrite: bool) -> None:
    context = get_context("spawn")
    before_fetch = context.Barrier(2)
    results = context.Queue()
    requests = [
        local_request(tmp_path, overwrite=overwrite),
        local_request(
            tmp_path,
            overwrite=overwrite,
            bounds=Bounds(west=-71.088, south=42.358, east=-71.087, north=42.359),
            origin=Origin(42.3585, -71.0875),
        ),
    ]
    workers = [
        context.Process(
            target=_run_concurrent_build,
            args=(request, before_fetch, results),
        )
        for request in requests
    ]

    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        outcomes = [results.get(timeout=2) for _ in workers]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()
        results.close()

    successes = [value for kind, value in outcomes if kind == "built"]
    errors = [value for kind, value in outcomes if kind == "error"]
    if overwrite:
        assert len(successes) == 2 and not errors
    else:
        assert len(successes) == len(errors) == 1
        assert "Output protection is enabled" in errors[0]

    plans = {request.origin.longitude: plan_map(request) for request in requests}
    for origin, installed_width, planned_width in successes:
        assert installed_width == planned_width == plans[origin["longitude"]].pixel_width
    tiff_path = tmp_path / "harbor" / "harbor.tif"
    report = verify_bundle(tiff_path)
    assert report.ok
    longitude = report.details["origin"]["longitude"]
    assert longitude in {origin["longitude"] for origin, _, _ in successes}
    assert report.details["pixel_width"] == plans[longitude].pixel_width
    snippet = tiff_path.with_suffix(".moos").read_text(encoding="utf-8")
    assert f"LongOrigin = {longitude:.10f}" in snippet


def test_rebuild_can_remove_previous_generated_snippet(tmp_path: Path) -> None:
    original = build_map(local_request(tmp_path), provider=FakeProvider())
    snippet = original.tiff_path.with_suffix(".moos")
    assert snippet.is_file()
    origin = Origin(latitude=42.36, longitude=-71.088)

    result = build_map(local_request(tmp_path, origin=origin, emit_moos=False), provider=FakeProvider())

    assert result.moos_path is None
    assert not snippet.exists()
    assert parse_info_file(result.info_path).origin == origin


def test_rebuild_preserves_edited_snippet_when_omitting_snippet(tmp_path: Path) -> None:
    original = build_map(local_request(tmp_path), provider=FakeProvider())
    snippet = original.tiff_path.with_suffix(".moos")
    edited = snippet.read_bytes() + b"\n// Mission-specific changes\n"
    snippet.write_bytes(edited)

    result = build_map(
        local_request(tmp_path, origin=Origin(42.36, -71.088), emit_moos=False),
        provider=FakeProvider(),
    )

    assert snippet.read_bytes() == edited
    assert any("Existing mission snippet was preserved" in warning for warning in result.plan.warnings)


@pytest.mark.parametrize("edit_during_fetch", [False, True])
def test_rebuild_refuses_to_overwrite_an_edited_snippet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, edit_during_fetch: bool
) -> None:
    request = local_request(tmp_path)
    original = build_map(request, provider=FakeProvider())
    snippet = original.tiff_path.with_suffix(".moos")
    edited = snippet.read_bytes() + b"\n// Mission-specific settings\n"
    before = (original.tiff_path.read_bytes(), original.info_path.read_bytes())
    provider = FakeProvider()

    if edit_during_fetch:
        fetch = service.fetch_tile_range

        def edit_then_fetch(*args, **kwargs):
            snippet.write_bytes(edited)
            return fetch(*args, **kwargs)

        monkeypatch.setattr(service, "fetch_tile_range", edit_then_fetch)
    else:
        snippet.write_bytes(edited)

    with pytest.raises(ValidationError, match="Existing mission file was preserved"):
        build_map(request, provider=provider)

    assert snippet.read_bytes() == edited
    assert (original.tiff_path.read_bytes(), original.info_path.read_bytes()) == before
    assert bool(provider.downloaded_tiles) == edit_during_fetch
    assert verify_bundle(original.tiff_path).ok


def test_failed_install_restores_prior_snippet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = build_map(local_request(tmp_path), provider=FakeProvider())
    snippet = original.tiff_path.with_suffix(".moos")
    before = {path: path.read_bytes() for path in (original.tiff_path, original.info_path, snippet)}

    def fail_installed_verification(path: Path, **options):
        report = verify_bundle(path, **options)
        if path == original.tiff_path:
            assert not snippet.exists()
            return replace(report, ok=False, errors=("simulated installation failure",))
        return report

    monkeypatch.setattr(service, "verify_bundle", fail_installed_verification)
    replacement = local_request(
        tmp_path,
        bounds=Bounds(west=-71.088, south=42.358, east=-71.087, north=42.359),
        origin=Origin(42.3585, -71.0875),
        emit_moos=False,
    )
    with pytest.raises(ValidationError, match="simulated installation failure"):
        build_map(replacement, provider=FakeProvider())

    assert {path: path.read_bytes() for path in before} == before


def _stop_after_installing_info(request: MapRequest) -> None:
    replace_file = os.replace
    final_info = request.output_dir / "harbor" / "harbor.info"

    def interrupted_replace(source, destination):
        replace_file(source, destination)
        if destination == final_info:
            os._exit(73)

    with patch.object(service.os, "replace", interrupted_replace):
        build_map(request, provider=FakeProvider())


def test_interrupted_rebuild_is_detected_and_recovered(tmp_path: Path) -> None:
    previous = build_map(local_request(tmp_path), provider=FakeProvider())
    before = {
        path: path.read_bytes()
        for path in (previous.tiff_path, previous.info_path, previous.tiff_path.with_suffix(".moos"))
    }
    attempted = local_request(
        tmp_path,
        bounds=Bounds(west=-71.088, south=42.358, east=-71.087, north=42.359),
        origin=Origin(42.3585, -71.0875),
    )
    process = get_context("spawn").Process(target=_stop_after_installing_info, args=(attempted,))
    process.start()
    try:
        process.join(timeout=10)
        assert process.exitcode == 73
    finally:
        if process.is_alive():
            process.terminate()
            process.join()

    assert previous.info_path.read_bytes() != before[previous.info_path]
    report = verify_bundle(previous.tiff_path)
    assert not report.ok and any("incomplete" in message for message in report.errors)

    with pytest.raises(ValidationError, match="Output protection is enabled"):
        build_map(replace(attempted, overwrite=False), provider=FakeProvider())
    assert verify_bundle(previous.tiff_path).ok
    assert {path: path.read_bytes() for path in before} == before

    replacement = build_map(attempted, provider=FakeProvider())
    assert replacement.verification["ok"]
    assert parse_info_file(replacement.info_path).origin == attempted.origin


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


def test_output_directory_is_validated_only_when_building(tmp_path: Path) -> None:
    invalid_output = tmp_path / "not-a-directory"
    invalid_output.write_text("file", encoding="utf-8")
    request = local_request(tmp_path, output_dir=invalid_output)

    assert plan_map(request).pixel_width == 512
    with pytest.raises(ValidationError, match="Output directory is not a directory"):
        build_map(request, provider=FakeProvider())


def test_outside_origin_is_allowed_with_warning(tmp_path: Path) -> None:
    request = local_request(
        tmp_path,
        origin=Origin(latitude=42.37, longitude=-71.087),
    )

    plan = plan_map(request)

    assert any("origin lies outside" in warning for warning in plan.warnings)


@pytest.mark.parametrize(
    "bounds",
    [
        Bounds(west=-71.1, south=42, east=-71.1 + 20_000 * 360 / (256 * (1 << 19)), north=42.0003),
        Bounds(west=0, south=0, east=0.0003, north=0.054),
    ],
)
def test_texture_warning_checks_each_side_and_suggests_a_lower_zoom(
    tmp_path: Path, bounds: Bounds
) -> None:
    origin = Origin((bounds.south + bounds.north) / 2, (bounds.west + bounds.east) / 2)
    request = local_request(tmp_path, bounds=bounds, origin=origin, zoom=19)

    plan = plan_map(request)
    warning = next(warning for warning in plan.warnings if "texture target" in warning)
    assert max(plan.pixel_width, plan.pixel_height) > 16_384
    assert "Zoom 18 is the highest available zoom" in warning

    exact_target = max(plan.pixel_width, plan.pixel_height)
    permitted = plan_map(replace(request, max_texture_dimension=exact_target))
    assert not any("texture target" in warning for warning in permitted.warnings)

    smaller = plan_map(replace(request, max_texture_dimension=8192))
    assert any("Zoom 17 is the highest available zoom" in warning for warning in smaller.warnings)


def test_cross_zone_map_is_planned_with_fixed_zone_geodesy(tmp_path: Path) -> None:
    request = local_request(
        tmp_path,
        bounds=Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1),
        origin=Origin(latitude=42.05, longitude=-72.0),
    )

    plan = plan_map(request)

    assert plan.pmarineviewer_width_m == pytest.approx(16_163.118, abs=0.01)
    assert plan.warnings == ()


def test_origin_and_map_center_may_use_different_utm_zones(tmp_path: Path) -> None:
    request = local_request(
        tmp_path,
        bounds=Bounds(west=-72.1, south=42.0, east=-71.9, north=42.1),
        origin=Origin(latitude=42.05, longitude=-72.05),
    )

    plan = plan_map(request)

    assert plan.estimated_max_pmarineviewer_position_error_m == pytest.approx(
        881.182, abs=0.01
    )
    assert plan.warnings == ()


def test_equator_crossing_map_is_planned_in_datum_hemisphere(
    tmp_path: Path,
) -> None:
    request = local_request(
        tmp_path,
        bounds=Bounds(west=-3.005, south=-0.005, east=-2.995, north=0.005),
        origin=Origin(latitude=0.0, longitude=-3.0),
    )

    plan = plan_map(request)

    assert plan.pmarineviewer_height_m == pytest.approx(1_105.300465, abs=0.001)
    assert plan.estimated_max_pmarineviewer_position_error_m < 0.001
    assert plan.warnings == ()
