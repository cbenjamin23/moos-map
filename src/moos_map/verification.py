from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .errors import ValidationError
from .geometry import crosses_utm_zone, utm_zone_number
from .moos_compat import estimate_pmarineviewer_placement
from .moos_files import parse_info_file


@dataclass(frozen=True, slots=True)
class VerificationReport:
    ok: bool
    tiff_path: Path
    info_path: Path
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tiff_path": str(self.tiff_path),
            "info_path": str(self.info_path),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "details": self.details,
        }


def verify_bundle(tiff_path: Path) -> VerificationReport:
    tiff_path = tiff_path.expanduser().resolve()
    info_path = tiff_path.with_suffix(".info")
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    if tiff_path.suffix != ".tif":
        errors.append("pMarineViewer requires the lowercase .tif suffix")
    if any(character.isspace() for character in tiff_path.name):
        errors.append("pMarineViewer rejects whitespace in tiff_file values")
    if not tiff_path.is_file():
        errors.append(f"TIFF file does not exist: {tiff_path}")
    else:
        try:
            with Image.open(tiff_path) as image:
                image.load()
                details.update(
                    {
                        "format": image.format,
                        "mode": image.mode,
                        "pixel_width": image.width,
                        "pixel_height": image.height,
                        "pixel_count": image.width * image.height,
                        "file_size_bytes": tiff_path.stat().st_size,
                        "estimated_pmarineviewer_cpu_gpu_bytes": (
                            image.width * image.height * 8
                        ),
                    }
                )
                if image.format != "TIFF":
                    errors.append(f"File contents are {image.format}, not TIFF")
                if image.width <= 0 or image.height <= 0:
                    errors.append("TIFF has invalid dimensions")
        except (UnidentifiedImageError, OSError) as exc:
            errors.append(f"TIFF cannot be decoded: {exc}")

    try:
        info = parse_info_file(info_path)
        details["bounds"] = info.bounds.as_dict()
        details["origin"] = info.origin.as_dict()
        details["info_comments"] = list(info.comments)
        if info.bounds.south < -80 or info.bounds.north > 84:
            errors.append("The .info bounds exceed the normal MOOS UTM latitude range")
        if crosses_utm_zone(info.bounds):
            errors.append("The .info bounds cross a UTM zone boundary")
        else:
            center_latitude = (info.bounds.north + info.bounds.south) / 2.0
            center_longitude = (info.bounds.east + info.bounds.west) / 2.0
            map_zone = utm_zone_number(center_longitude, center_latitude)
            origin_zone = utm_zone_number(info.origin.longitude, info.origin.latitude)
            if map_zone != origin_zone:
                errors.append(
                    f"The .info origin is in UTM zone {origin_zone}, while the image "
                    f"is in zone {map_zone}"
                )
            else:
                placement = estimate_pmarineviewer_placement(info.bounds, info.origin)
                details["pmarineviewer_estimate"] = {
                    "width_m": placement.width_m,
                    "height_m": placement.height_m,
                    "image_center_local_x_m": placement.image_center_x_m,
                    "image_center_local_y_m": placement.image_center_y_m,
                    "estimated_max_position_error_m": (placement.max_position_error_m),
                }
        if not info.bounds.contains(info.origin.latitude, info.origin.longitude):
            warnings.append(
                "The .info datum/origin is outside the image bounds; this is valid if "
                "it matches the mission's LatOrigin/LongOrigin"
            )
    except ValidationError as exc:
        errors.append(str(exc))

    return VerificationReport(
        ok=not errors,
        tiff_path=tiff_path,
        info_path=info_path,
        errors=tuple(errors),
        warnings=tuple(warnings),
        details=details,
    )
