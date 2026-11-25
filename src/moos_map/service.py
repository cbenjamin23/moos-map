from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from . import __version__
from .acquisition import (
    ProgressCallback,
    TileProvider,
    create_provider,
    fetch_tile_range,
)
from .errors import SourcePolicyError, ValidationError
from .geometry import (
    approximate_ground_size,
    bounds_for_tile_range,
    estimate_vertical_mapping_error_for_bounds,
    meters_per_pixel,
    pixel_window_for_bounds,
    tile_range_for_bounds,
)
from .models import BuildResult, MapPlan, MapRequest
from .moos_compat import estimate_pmarineviewer_placement
from .moos_files import (
    moos_snippet_text,
    parse_info_file,
    tiff_binding,
    write_info_file,
    write_moos_snippet,
)
from .raster import crop_to_pixel_window, save_tiff_atomic, stitch_tiles
from .sources import MapSource, mbtiles_coverage, resolve_source
from .verification import VerificationReport, install_journal_path, verify_bundle


NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def normalize_map_name(name: str) -> str:
    value = name.strip()
    if value.lower().endswith(".tif"):
        value = value[:-4]
    if not value or not NAME_PATTERN.fullmatch(value):
        raise ValidationError(
            "Map name must begin with a letter or number and contain only "
            "letters, numbers, dot, underscore, or hyphen"
        )
    if value in {".", ".."}:
        raise ValidationError("Invalid map name")
    return value


def prepare_bundle_directory(output_directory: Path, map_name: str) -> Path:
    """Create and validate a writable per-map output directory."""

    try:
        output_root = output_directory.expanduser().resolve()
        if output_root.exists() and not output_root.is_dir():
            raise ValidationError(
                f"Output directory is not a directory: {output_root}"
            )
        output_root.mkdir(parents=True, exist_ok=True)

        bundle_directory = output_root / map_name
        if bundle_directory.exists() and not bundle_directory.is_dir():
            raise ValidationError(
                f"Map bundle path is not a directory: {bundle_directory}"
            )
        bundle_directory.mkdir(exist_ok=True)

        with tempfile.NamedTemporaryFile(
            prefix=".moos-map-write-test-", dir=bundle_directory
        ):
            pass
    except ValidationError:
        raise
    except (OSError, RuntimeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        raise ValidationError(
            f"Cannot create or write to output directory '{output_directory}': {reason}"
        ) from exc

    return bundle_directory


def resolve_request_source(request: MapRequest) -> MapSource:
    return resolve_source(
        request.source_id,
        custom_url_template=request.custom_url_template,
        accept_custom_source_terms=request.accept_custom_source_terms,
        mbtiles_path=request.mbtiles_path,
    )


def _highest_zoom_for_texture_target(request: MapRequest, source: MapSource) -> int | None:
    for zoom in range(request.zoom - 1, source.min_zoom - 1, -1):
        if source.available_zooms is not None and zoom not in source.available_zooms:
            continue
        tiles = tile_range_for_bounds(request.bounds, zoom)
        if tiles.count > request.max_tiles:
            continue
        try:
            crop = pixel_window_for_bounds(request.bounds, tiles, source.tile_size)
        except ValidationError:
            continue
        if (
            max(crop.output_width, crop.output_height) > request.max_texture_dimension
            or crop.output_width * crop.output_height > request.max_pixels
        ):
            continue
        if source.mbtiles_path and mbtiles_coverage(source.mbtiles_path, tiles) != tiles.count:
            continue
        return zoom
    return None


def plan_map(
    request: MapRequest,
    source: MapSource | None = None,
) -> MapPlan:
    source = source or resolve_request_source(request)
    if request.max_tiles < 1:
        raise ValidationError("Maximum tile count must be at least one")
    if request.max_texture_dimension < 1:
        raise ValidationError("Target texture dimension must be at least one pixel")
    if request.max_pixels < source.tile_size * source.tile_size:
        raise ValidationError(
            f"Maximum pixel count must allow at least one {source.tile_size}x"
            f"{source.tile_size} tile"
        )
    if request.bounds.south < -80 or request.bounds.north > 84:
        raise ValidationError("MOOS UTM map placement is limited to 80°S through 84°N")
    if source.available_zooms is not None and request.zoom not in source.available_zooms:
        levels = ", ".join(str(zoom) for zoom in source.available_zooms)
        raise ValidationError(f"MBTiles archive has no tiles at zoom {request.zoom}. Available zoom levels: {levels}")
    if not source.min_zoom <= request.zoom <= source.max_zoom:
        raise ValidationError(
            f"Source '{source.id}' supports zoom {source.min_zoom} through "
            f"{source.max_zoom}, not {request.zoom}"
        )
    tiles = tile_range_for_bounds(request.bounds, request.zoom)
    download_bounds = bounds_for_tile_range(tiles)
    actual_bounds = request.bounds
    requested_width, requested_height = approximate_ground_size(request.bounds)
    actual_width, actual_height = requested_width, requested_height
    crop = pixel_window_for_bounds(request.bounds, tiles, source.tile_size)
    pixel_width = crop.output_width
    pixel_height = crop.output_height
    center_latitude = (actual_bounds.north + actual_bounds.south) / 2.0
    if (
        source.mbtiles_path is not None
        and tiles.count <= request.max_tiles
        and pixel_width * pixel_height <= request.max_pixels
    ):
        covered = mbtiles_coverage(source.mbtiles_path, tiles)
        if covered != tiles.count:
            raise ValidationError(
                f"MBTiles archive covers {covered} of {tiles.count} requested tiles at zoom "
                f"{tiles.zoom}. Choose a region with complete tile coverage."
            )

    warnings: list[str] = []
    if not source.export_allowed:
        warnings.append(
            f"Source '{source.name}' is preview-only and cannot be exported"
        )
    if not actual_bounds.contains(request.origin.latitude, request.origin.longitude):
        warnings.append(
            "Mission origin lies outside the TIFF; this is valid, but confirm it matches "
            "the mission's LatOrigin/LongOrigin"
        )
    if tiles.count > request.max_tiles:
        warnings.append(
            f"Plan uses {tiles.count} tiles, above the configured limit of "
            f"{request.max_tiles}"
        )
    if pixel_width * pixel_height > request.max_pixels:
        warnings.append(
            f"Plan creates {pixel_width * pixel_height:,} pixels, above the configured "
            f"limit of {request.max_pixels:,}"
        )
    if max(pixel_width, pixel_height) > request.max_texture_dimension:
        zoom = _highest_zoom_for_texture_target(request, source)
        suggestion = (
            f"Zoom {zoom} is the highest available zoom that fits the target and build limits."
            if zoom is not None else "Choose a smaller region or a source with a suitable zoom."
        )
        warnings.append(
            f"The {pixel_width:,} × {pixel_height:,} px TIFF exceeds the pMarineViewer "
            f"texture target of {request.max_texture_dimension:,} px per side. {suggestion}"
        )
    width_ratio = 1.0
    height_ratio = 1.0
    mapping_error = estimate_vertical_mapping_error_for_bounds(actual_bounds)
    resolution = meters_per_pixel(center_latitude, request.zoom, source.tile_size)
    viewer = estimate_pmarineviewer_placement(
        actual_bounds,
        request.origin,
        requested_bounds=request.bounds,
    )
    source_report = source.as_dict()
    if source.id == "custom":
        source_report["url_template"] = None

    return MapPlan(
        source=source_report,
        requested_bounds=request.bounds,
        actual_bounds=actual_bounds,
        download_bounds=download_bounds,
        origin=request.origin,
        tiles=tiles,
        crop=crop,
        tile_size=source.tile_size,
        pixel_width=pixel_width,
        pixel_height=pixel_height,
        approximate_meters_per_pixel=resolution,
        approximate_ground_width_m=actual_width,
        approximate_ground_height_m=actual_height,
        estimated_max_vertical_mapping_error_m=mapping_error,
        pmarineviewer_width_m=viewer.width_m,
        pmarineviewer_height_m=viewer.height_m,
        image_center_local_x_m=viewer.image_center_x_m,
        image_center_local_y_m=viewer.image_center_y_m,
        estimated_max_pmarineviewer_position_error_m=viewer.max_position_error_m,
        estimated_max_requested_area_position_error_m=(
            viewer.requested_area_max_position_error_m
        ),
        expansion_width_ratio=width_ratio,
        expansion_height_ratio=height_ratio,
        warnings=tuple(warnings),
    )


def _check_existing_outputs(targets: list[Path]) -> None:
    existing = [path for path in targets if path.exists() or path.is_symlink()]
    if existing:
        raise ValidationError(
            "Output protection is enabled and these files already exist: "
            + ", ".join(str(path) for path in existing)
        )


def _is_previous_generated_snippet(
    moos_path: Path, tiff_path: Path, info_path: Path
) -> bool:
    try:
        if moos_path.is_symlink() or not moos_path.is_file():
            return False
        origin = parse_info_file(info_path).origin
        expected = moos_snippet_text(tiff_name=tiff_path.name, origin=origin).encode(
            "utf-8"
        )
        return (
            moos_path.stat().st_size == len(expected)
            and moos_path.read_bytes() == expected
        )
    except (OSError, ValidationError):
        return False


def _check_snippet_can_be_replaced(moos_path: Path, tiff_path: Path, info_path: Path) -> None:
    if (moos_path.exists() or moos_path.is_symlink()) and not _is_previous_generated_snippet(
        moos_path, tiff_path, info_path
    ):
        raise ValidationError(
            f"Existing mission file was preserved at {moos_path}. "
            "Choose a different map name or omit mission snippet generation."
        )


def _restore_outputs(journal: Path, originals: dict[Path, bool]) -> None:
    for target, existed in reversed(list(originals.items())):
        if existed:
            # Keep the backup intact so recovery can resume after another interruption.
            backup = journal / "backups" / target.name
            temporary = journal / "restoring"
            temporary.unlink(missing_ok=True)
            shutil.copy2(backup, temporary, follow_symlinks=False)
            os.replace(temporary, target)
        else:
            target.unlink(missing_ok=True)


def _recover_interrupted_install(tiff_path: Path) -> None:
    journal = install_journal_path(tiff_path)
    if not journal.exists():
        return
    required = {tiff_path.name, tiff_path.with_suffix(".info").name}
    allowed = required | {tiff_path.with_suffix(".moos").name}
    try:
        manifest = json.loads((journal / "originals.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not required <= manifest.keys() <= allowed:
            raise ValueError("unexpected output names")
        for name, existed in manifest.items():
            if not isinstance(existed, bool):
                raise ValueError("invalid backup record")
            backup = journal / "backups" / name
            if existed and not (backup.is_file() or backup.is_symlink()):
                raise ValueError(f"missing backup for {name}")
        _restore_outputs(journal, {journal.parent / name: v for name, v in manifest.items()})
        # Remove the install marker atomically before cleaning out its backups.
        with tempfile.TemporaryDirectory(prefix=".moos-map-recovery-", dir=journal.parent) as directory:
            os.replace(journal, Path(directory) / "recovered")
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Cannot recover interrupted map installation at {journal}: {exc}") from exc


def _install_bundle(
    staging_dir: Path,
    staged_targets: list[tuple[Path | None, Path]],
    tiff_path: Path,
) -> VerificationReport:
    journal = install_journal_path(tiff_path)
    backups = staging_dir / "backups"
    backups.mkdir()
    originals: dict[Path, bool] = {}
    for _, target in staged_targets:
        originals[target] = target.exists() or target.is_symlink()
        if originals[target]:
            shutil.copy2(target, backups / target.name, follow_symlinks=False)
    (staging_dir / "originals.json").write_text(
        json.dumps({path.name: existed for path, existed in originals.items()}), encoding="utf-8"
    )
    # Publish the recovery journal before replacing any live files.
    os.replace(staging_dir, journal)

    changed: list[Path] = []
    try:
        for staged, target in staged_targets:
            if staged is None:
                target.unlink()
            else:
                os.replace(journal / staged.name, target)
            changed.append(target)
        report = verify_bundle(tiff_path, check_interrupted=False)
        if not report.ok:
            raise ValidationError(
                "Installed bundle failed verification: " + "; ".join(report.errors)
            )
        os.replace(journal, staging_dir)
    except BaseException:
        if journal.exists():
            _restore_outputs(journal, {target: originals[target] for target in changed})
            os.replace(journal, staging_dir)
        raise
    return report


def build_map(
    request: MapRequest,
    *,
    progress: ProgressCallback | None = None,
    provider: TileProvider | None = None,
) -> BuildResult:
    source = resolve_request_source(request)
    plan = plan_map(request, source)
    if not source.export_allowed:
        raise SourcePolicyError(
            f"Source '{source.name}' is preview-only. Select an export-permitted source."
        )
    if plan.tiles.count > request.max_tiles:
        raise ValidationError(
            f"Build requires {plan.tiles.count} tiles; limit is {request.max_tiles}"
        )
    if plan.pixel_count > request.max_pixels:
        raise ValidationError(
            f"Build requires {plan.pixel_count:,} pixels; limit is {request.max_pixels:,}"
        )

    name = normalize_map_name(request.name)
    output_dir = prepare_bundle_directory(request.output_dir, name)
    tiff_path = output_dir / f"{name}.tif"
    info_path = output_dir / f"{name}.info"
    moos_path = output_dir / f"{name}.moos"
    targets = [tiff_path, info_path] + ([moos_path] if request.emit_moos else [])
    lock = FileLock(str(output_dir / ".moos-map.lock"))
    with lock:
        _recover_interrupted_install(tiff_path)
        if not request.overwrite_outputs:
            _check_existing_outputs(targets)
        if request.emit_moos:
            _check_snippet_can_be_replaced(moos_path, tiff_path, info_path)

    owns_provider = provider is None
    active_provider = provider or create_provider(source)
    try:
        tile_data = fetch_tile_range(
            active_provider,
            plan.tiles,
            force=request.refresh_source_tiles,
            progress=progress,
        )
        with tempfile.TemporaryDirectory(
            prefix=f".{name}.building-", dir=output_dir
        ) as temporary_name:
            staging_dir = Path(temporary_name)
            staged_tiff = staging_dir / tiff_path.name
            staged_info = staging_dir / info_path.name
            staged_moos = staging_dir / moos_path.name if request.emit_moos else None
            export_id = uuid4().hex
            description = tiff_binding(
                export_id, plan.actual_bounds, request.origin,
                viewer_longitude=plan.actual_bounds.longitude_near_center(request.origin.longitude),
            )

            stitched_image = stitch_tiles(tile_data, plan.tiles, source.tile_size)
            try:
                image = crop_to_pixel_window(stitched_image, plan.crop)
                try:
                    save_tiff_atomic(image, staged_tiff, description=description)
                finally:
                    image.close()
            finally:
                stitched_image.close()

            write_info_file(
                staged_info,
                actual_bounds=plan.actual_bounds,
                origin=request.origin,
                source_id=source.id,
                source_attribution=source.attribution,
                zoom=request.zoom,
                requested_bounds=request.bounds,
                generator_version=__version__,
                export_id=export_id,
            )
            if staged_moos:
                write_moos_snippet(
                    staged_moos,
                    tiff_name=tiff_path.name,
                    origin=request.origin,
                )

            staged_report = verify_bundle(staged_tiff)
            if not staged_report.ok:
                raise ValidationError(
                    "Generated bundle failed verification: "
                    + "; ".join(staged_report.errors)
                )

            with lock:
                _recover_interrupted_install(tiff_path)
                if not request.overwrite_outputs:
                    _check_existing_outputs(targets)
                staged_targets: list[tuple[Path | None, Path]] = [
                    (staged_info, info_path),
                    (staged_tiff, tiff_path),
                ]
                if staged_moos:
                    _check_snippet_can_be_replaced(moos_path, tiff_path, info_path)
                    staged_targets.append((staged_moos, moos_path))
                elif moos_path.exists() or moos_path.is_symlink():
                    if _is_previous_generated_snippet(moos_path, tiff_path, info_path):
                        staged_targets.append((None, moos_path))
                    else:
                        warning = (
                            f"Existing mission snippet was preserved at {moos_path}. "
                            "Check its origin and TIFF name before using it."
                        )
                        plan = replace(plan, warnings=(*plan.warnings, warning))
                report = _install_bundle(staging_dir, staged_targets, tiff_path)

        return BuildResult(
            plan=plan,
            tiff_path=tiff_path,
            info_path=info_path,
            moos_path=moos_path if request.emit_moos else None,
            cache_hits=active_provider.cache_hits,
            downloaded_tiles=active_provider.downloaded_tiles,
            verification=report.as_dict(),
        )
    finally:
        if owns_provider:
            active_provider.close()
