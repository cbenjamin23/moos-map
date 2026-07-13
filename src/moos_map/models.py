from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .errors import ValidationError


WEB_MERCATOR_MAX_LAT = 85.0511287798066


@dataclass(frozen=True, slots=True)
class Bounds:
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        values = (self.west, self.south, self.east, self.north)
        if not all(isinstance(value, (int, float)) for value in values):
            raise ValidationError("Bounds must be numeric")
        if not -180 <= self.west <= 180 or not -180 <= self.east <= 180:
            raise ValidationError("Longitude bounds must be between -180 and 180")
        if not -WEB_MERCATOR_MAX_LAT <= self.south <= WEB_MERCATOR_MAX_LAT:
            raise ValidationError(
                f"South latitude must be within Web Mercator limits (+/-{WEB_MERCATOR_MAX_LAT:.6f})"
            )
        if not -WEB_MERCATOR_MAX_LAT <= self.north <= WEB_MERCATOR_MAX_LAT:
            raise ValidationError(
                f"North latitude must be within Web Mercator limits (+/-{WEB_MERCATOR_MAX_LAT:.6f})"
            )
        if self.west >= self.east:
            raise ValidationError(
                "West must be less than east; antimeridian-crossing bounds are not supported"
            )
        if self.south >= self.north:
            raise ValidationError("South must be less than north")

    def contains(self, latitude: float, longitude: float) -> bool:
        return (
            self.south <= latitude <= self.north and self.west <= longitude <= self.east
        )

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Origin:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValidationError("Origin latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValidationError("Origin longitude must be between -180 and 180")

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TileRange:
    zoom: int
    x_min: int
    x_max: int
    y_min: int
    y_max: int

    @property
    def columns(self) -> int:
        return self.x_max - self.x_min + 1

    @property
    def rows(self) -> int:
        return self.y_max - self.y_min + 1

    @property
    def count(self) -> int:
        return self.columns * self.rows

    def coordinates(self) -> Iterator[tuple[int, int]]:
        for y in range(self.y_min, self.y_max + 1):
            for x in range(self.x_min, self.x_max + 1):
                yield x, y

    def as_dict(self) -> dict[str, int]:
        return {
            "zoom": self.zoom,
            "x_min": self.x_min,
            "x_max": self.x_max,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "columns": self.columns,
            "rows": self.rows,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class PixelWindow:
    left: float
    top: float
    right: float
    bottom: float
    output_width: int
    output_height: int

    @property
    def source_width(self) -> float:
        return self.right - self.left

    @property
    def source_height(self) -> float:
        return self.bottom - self.top

    def as_dict(self) -> dict[str, float | int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "output_width": self.output_width,
            "output_height": self.output_height,
        }


@dataclass(frozen=True, slots=True)
class MapRequest:
    bounds: Bounds
    origin: Origin
    zoom: int
    source_id: str = "google-satellite"
    name: str = "moos_map"
    output_dir: Path = field(default_factory=lambda: Path.home() / "moos-maps")
    emit_moos: bool = False
    force: bool = False
    custom_url_template: str | None = None
    accept_custom_source_terms: bool = False
    mbtiles_path: Path | None = None
    max_tiles: int = 1024
    max_pixels: int = 67_108_864


@dataclass(frozen=True, slots=True)
class MapPlan:
    source: dict[str, Any]
    requested_bounds: Bounds
    actual_bounds: Bounds
    download_bounds: Bounds
    origin: Origin
    tiles: TileRange
    crop: PixelWindow
    tile_size: int
    pixel_width: int
    pixel_height: int
    approximate_meters_per_pixel: float
    approximate_ground_width_m: float
    approximate_ground_height_m: float
    estimated_max_vertical_mapping_error_m: float
    pmarineviewer_width_m: float
    pmarineviewer_height_m: float
    image_center_local_x_m: float
    image_center_local_y_m: float
    estimated_max_pmarineviewer_position_error_m: float
    estimated_max_requested_area_position_error_m: float
    expansion_width_ratio: float
    expansion_height_ratio: float
    warnings: tuple[str, ...] = ()

    @property
    def pixel_count(self) -> int:
        return self.pixel_width * self.pixel_height

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "requested_bounds": self.requested_bounds.as_dict(),
            "actual_bounds": self.actual_bounds.as_dict(),
            "download_bounds": self.download_bounds.as_dict(),
            "origin": self.origin.as_dict(),
            "tiles": self.tiles.as_dict(),
            "crop": self.crop.as_dict(),
            "tile_size": self.tile_size,
            "pixel_width": self.pixel_width,
            "pixel_height": self.pixel_height,
            "pixel_count": self.pixel_count,
            "approximate_meters_per_pixel": self.approximate_meters_per_pixel,
            "approximate_ground_width_m": self.approximate_ground_width_m,
            "approximate_ground_height_m": self.approximate_ground_height_m,
            "estimated_max_vertical_mapping_error_m": (
                self.estimated_max_vertical_mapping_error_m
            ),
            "pmarineviewer_width_m": self.pmarineviewer_width_m,
            "pmarineviewer_height_m": self.pmarineviewer_height_m,
            "image_center_local_x_m": self.image_center_local_x_m,
            "image_center_local_y_m": self.image_center_local_y_m,
            "estimated_max_pmarineviewer_position_error_m": (
                self.estimated_max_pmarineviewer_position_error_m
            ),
            "estimated_max_requested_area_position_error_m": (
                self.estimated_max_requested_area_position_error_m
            ),
            "expansion_width_ratio": self.expansion_width_ratio,
            "expansion_height_ratio": self.expansion_height_ratio,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class BuildResult:
    plan: MapPlan
    tiff_path: Path
    info_path: Path
    moos_path: Path | None
    cache_hits: int
    downloaded_tiles: int
    verification: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.as_dict(),
            "tiff_path": str(self.tiff_path),
            "info_path": str(self.info_path),
            "moos_path": str(self.moos_path) if self.moos_path else None,
            "cache_hits": self.cache_hits,
            "downloaded_tiles": self.downloaded_tiles,
            "verification": self.verification,
        }
