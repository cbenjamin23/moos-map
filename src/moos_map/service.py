from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

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
    crosses_utm_zone,
    estimate_vertical_mapping_error_for_bounds,
    meters_per_pixel,
    pixel_window_for_bounds,
    tile_range_for_bounds,
    utm_zone_number,
)
from .models import BuildResult, MapPlan, MapRequest
from .moos_compat import estimate_pmarineviewer_placement
from .moos_files import write_info_file, write_moos_snippet
from .raster import crop_to_pixel_window, save_tiff_atomic, stitch_tiles
from .sources import MapSource, resolve_source
from .verification import verify_bundle


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


def plan_map(
    request: MapRequest,
    source: MapSource | None = None,
) -> MapPlan:
    source = source or resolve_request_source(request)
    if request.max_tiles < 1:
        raise ValidationError("Maximum tile count must be at least one")
    if request.max_pixels < source.tile_size * source.tile_size:
        raise ValidationError(
            f"Maximum pixel count must allow at least one {source.tile_size}x"
            f"{source.tile_size} tile"
        )
    if request.bounds.south < -80 or request.bounds.north > 84:
        raise ValidationError("MOOS UTM map placement is limited to 80°S through 84°N")
    if crosses_utm_zone(request.bounds):
        raise ValidationError(
            "Requested bounds cross a UTM zone boundary; choose a smaller region"
        )
    if not source.min_zoom <= request.zoom <= source.max_zoom:
        raise ValidationError(
            f"Source '{source.id}' supports zoom {source.min_zoom} through "
            f"{source.max_zoom}, not {request.zoom}"
        )
    tiles = tile_range_for_bounds(request.bounds, request.zoom)
    download_bounds = bounds_for_tile_range(tiles)
    actual_bounds = request.bounds
    map_center_latitude = (actual_bounds.north + actual_bounds.south) / 2.0
    map_center_longitude = (actual_bounds.east + actual_bounds.west) / 2.0
    map_zone = utm_zone_number(map_center_longitude, map_center_latitude)
    origin_zone = utm_zone_number(request.origin.longitude, request.origin.latitude)
    if map_zone != origin_zone:
        raise ValidationError(
            f"Mission origin is in UTM zone {origin_zone}, but the TIFF is in zone "
            f"{map_zone}; current MOOS geodesy cannot place this reliably"
        )
    requested_width, requested_height = approximate_ground_size(request.bounds)
    actual_width, actual_height = requested_width, requested_height
    crop = pixel_window_for_bounds(request.bounds, tiles, source.tile_size)
    pixel_width = crop.output_width
    pixel_height = crop.output_height
    center_latitude = map_center_latitude

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
    width_ratio = 1.0
    height_ratio = 1.0
    mapping_error = estimate_vertical_mapping_error_for_bounds(actual_bounds)
    resolution = meters_per_pixel(center_latitude, request.zoom, source.tile_size)
    viewer = estimate_pmarineviewer_placement(
        actual_bounds,
        request.origin,
        requested_bounds=request.bounds,
    )

    return MapPlan(
        source=source.as_dict(),
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
    moos_path = output_dir / f"{name}.moos" if request.emit_moos else None
    targets = [tiff_path, info_path] + ([moos_path] if moos_path else [])
    existing = [path for path in targets if path and path.exists()]
    if existing and not request.overwrite_outputs:
        raise ValidationError(
            "Output protection is enabled and these files already exist: "
            + ", ".join(str(path) for path in existing)
        )

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
            staged_moos = staging_dir / moos_path.name if moos_path else None

            stitched_image = stitch_tiles(tile_data, plan.tiles, source.tile_size)
            try:
                image = crop_to_pixel_window(stitched_image, plan.crop)
                try:
                    save_tiff_atomic(image, staged_tiff)
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
            )
            if staged_moos:
                write_moos_snippet(
                    staged_moos,
                    tiff_name=tiff_path.name,
                    origin=request.origin,
                    pixel_width=plan.pixel_width,
                    pixel_height=plan.pixel_height,
                )

            staged_report = verify_bundle(staged_tiff)
            if not staged_report.ok:
                raise ValidationError(
                    "Generated bundle failed verification: "
                    + "; ".join(staged_report.errors)
                )

            staged_targets = [(staged_info, info_path), (staged_tiff, tiff_path)]
            if staged_moos and moos_path:
                staged_targets.append((staged_moos, moos_path))

            backups: dict[Path, Path] = {}
            for _, target in staged_targets:
                if target.exists():
                    backup = staging_dir / f"backup-{target.name}"
                    shutil.copy2(target, backup)
                    backups[target] = backup

            replaced: list[Path] = []
            try:
                for staged, target in staged_targets:
                    os.replace(staged, target)
                    replaced.append(target)
                report = verify_bundle(tiff_path)
                if not report.ok:
                    raise ValidationError(
                        "Installed bundle failed verification: "
                        + "; ".join(report.errors)
                    )
            except Exception:
                for target in reversed(replaced):
                    backup = backups.get(target)
                    if backup and backup.exists():
                        os.replace(backup, target)
                    else:
                        target.unlink(missing_ok=True)
                raise

        return BuildResult(
            plan=plan,
            tiff_path=tiff_path,
            info_path=info_path,
            moos_path=moos_path,
            cache_hits=active_provider.cache_hits,
            downloaded_tiles=active_provider.downloaded_tiles,
            verification=report.as_dict(),
        )
    finally:
        if owns_provider:
            active_provider.close()
