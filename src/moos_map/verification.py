from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .errors import ValidationError
from .moos_compat import estimate_pmarineviewer_placement
from .models import Origin
from .moos_files import (
    EXPORT_ID_PREFIX,
    MOOS_SNIPPET_HEADER,
    TIFF_BINDING_PREFIX,
    parse_info_file,
    tiff_binding,
)


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


def install_journal_path(tiff_path: Path) -> Path:
    return tiff_path.with_name(f".{tiff_path.name}.installing")


def _generated_snippet_warning(tiff_path: Path, origin: Origin) -> str | None:
    snippet = tiff_path.with_suffix(".moos")
    fields: dict[str, list[str]] = {"latorigin": [], "longorigin": [], "tiff_file": []}
    try:
        if not snippet.is_file():
            return None
        with snippet.open(encoding="utf-8") as stream:
            if stream.readline().strip() != MOOS_SNIPPET_HEADER:
                return None
            for line in stream:
                key, _, value = line.split("//", 1)[0].partition("=")
                key = key.strip().lower()
                if key in fields:
                    fields[key].append(value.strip())
    except (OSError, UnicodeError):
        return None

    discrepancies = []
    for name, expected in (("LatOrigin", origin.latitude), ("LongOrigin", origin.longitude)):
        values = fields[name.lower()]
        try:
            matches = len(values) == 1 and math.isclose(
                float(values[0]), expected, rel_tol=0, abs_tol=1e-10
            )
        except ValueError:
            matches = False
        if not matches:
            discrepancies.append(name)
    if [value.strip('"') for value in fields["tiff_file"]] != [tiff_path.name]:
        discrepancies.append("tiff_file")
    if discrepancies:
        return (
            f"Generated mission snippet {snippet.name} disagrees with the map's "
            f"{', '.join(discrepancies)}. Use the snippet from the matching export."
        )
    return None


def verify_bundle(
    tiff_path: Path, *, check_interrupted: bool = True
) -> VerificationReport:
    requested_path = tiff_path.expanduser().absolute()
    tiff_path = requested_path.resolve()
    info_path = tiff_path.with_suffix(".info")
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    binding = None
    journals = {install_journal_path(requested_path), install_journal_path(tiff_path)}

    if check_interrupted and any(journal.exists() for journal in journals):
        return VerificationReport(
            ok=False,
            tiff_path=tiff_path,
            info_path=info_path,
            errors=("Bundle installation is incomplete. Rebuild the same map to recover it.",),
            warnings=(),
            details={},
        )

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
                if image.format == "TIFF":
                    description = image.tag_v2.get(270)
                    if isinstance(description, str) and description.startswith(TIFF_BINDING_PREFIX):
                        binding = description
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
        export_ids = [comment.removeprefix(EXPORT_ID_PREFIX) for comment in info.comments
                      if comment.startswith(EXPORT_ID_PREFIX)]
        if binding is not None or export_ids:
            if len(export_ids) != 1 or binding != tiff_binding(
                export_ids[0], info.bounds, info.origin, viewer_longitude=info.viewer_longitude
            ):
                errors.append("TIFF and .info placement metadata do not match. Use the pair from the same export.")
        if info.bounds.south < -80 or info.bounds.north > 84:
            errors.append("The .info bounds exceed the normal MOOS UTM latitude range")
        placement = estimate_pmarineviewer_placement(
            info.bounds, info.origin, viewer_longitude=info.viewer_longitude
        )
        if info.bounds.longitude_near_center(info.viewer_longitude) != info.viewer_longitude:
            warnings.append("The stored viewer datum crosses the date line. Rebuild the map to correct its placement.")
        details["pmarineviewer_estimate"] = {
            "width_m": placement.width_m,
            "height_m": placement.height_m,
            "image_center_local_x_m": placement.image_center_x_m,
            "image_center_local_y_m": placement.image_center_y_m,
            "estimated_max_position_error_m": placement.max_position_error_m,
        }
        if not info.bounds.contains(info.origin.latitude, info.origin.longitude):
            warnings.append(
                "The .info datum/origin is outside the image bounds; this is valid if "
                "it matches the mission's LatOrigin/LongOrigin"
            )
        snippet_warning = _generated_snippet_warning(tiff_path, info.origin)
        if snippet_warning:
            warnings.append(snippet_warning)
    except ValidationError as exc:
        errors.append(str(exc))

    if check_interrupted and any(journal.exists() for journal in journals):
        errors.append("Bundle installation began during verification. Retry verification.")

    return VerificationReport(
        ok=not errors,
        tiff_path=tiff_path,
        info_path=info_path,
        errors=tuple(errors),
        warnings=tuple(warnings),
        details=details,
    )
