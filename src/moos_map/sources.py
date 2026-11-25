from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from string import Formatter
from typing import Any

from .errors import FetchError, ValidationError
from .models import TileRange


@dataclass(frozen=True, slots=True)
class MapSource:
    id: str
    name: str
    kind: str
    tile_size: int
    min_zoom: int
    max_zoom: int
    url_template: str | None
    preview_allowed: bool
    export_allowed: bool
    attribution: str
    terms_url: str | None
    coverage: str
    note: str = ""
    mbtiles_path: Path | None = None
    url_zoom_offset: int = 0
    available_zooms: tuple[int, ...] | None = None

    def tile_url(self, zoom: int, x: int, y: int) -> str:
        if self.kind != "xyz" or not self.url_template:
            raise ValidationError(f"Source {self.id} does not provide XYZ URLs")
        source_zoom = zoom + self.url_zoom_offset
        return self.url_template.format(z=zoom, source_z=source_zoom, x=x, y=y)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["mbtiles_path"] = str(self.mbtiles_path) if self.mbtiles_path else None
        return result


BUILTIN_SOURCES: dict[str, MapSource] = {
    "google-maps": MapSource(
        id="google-maps",
        name="Google Maps",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=22,
        url_template="https://mt.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        preview_allowed=True,
        export_allowed=True,
        attribution="Google",
        terms_url="https://www.google.com/help/terms_maps/",
        coverage="Global",
        note="Street map with roads, places, and local features. Native detail varies by location.",
    ),
    "google-satellite": MapSource(
        id="google-satellite",
        name="Google Satellite",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=22,
        url_template="https://mt.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        preview_allowed=True,
        export_allowed=True,
        attribution="Google",
        terms_url="https://www.google.com/help/terms_maps/",
        coverage="Global",
        note="High-resolution aerial and satellite imagery. Native detail varies by location.",
    ),
    "google-hybrid": MapSource(
        id="google-hybrid",
        name="Google Satellite Hybrid",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=22,
        url_template="https://mt.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        preview_allowed=True,
        export_allowed=True,
        attribution="Google",
        terms_url="https://www.google.com/help/terms_maps/",
        coverage="Global",
        note="Satellite imagery with roads and place labels.",
    ),
    "esri-world-imagery": MapSource(
        id="esri-world-imagery",
        name="Esri World Imagery",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=21,
        url_template=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        preview_allowed=True,
        export_allowed=True,
        attribution="Esri, Maxar, Earthstar Geographics, and contributors",
        terms_url="https://www.esri.com/en-us/legal/terms/full-master-agreement",
        coverage="Global",
        note="High-resolution satellite and aerial imagery. Native detail varies by location.",
    ),
    "esri-world-topo": MapSource(
        id="esri-world-topo",
        name="Esri World Topographic Map",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=19,
        url_template=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
        ),
        preview_allowed=True,
        export_allowed=True,
        attribution="Esri and contributors",
        terms_url="https://www.esri.com/en-us/legal/terms/full-master-agreement",
        coverage="Global",
        note="Topographic map with terrain, hydrography, roads, and place labels.",
    ),
}


def list_sources() -> list[MapSource]:
    return list(BUILTIN_SOURCES.values())


def open_mbtiles(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    connection = None
    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=check_same_thread
        )
        connection.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles LIMIT 0")
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise FetchError(f"Invalid MBTiles archive {path}: {exc}") from exc
    return connection


def _mbtiles_zooms(path: Path) -> tuple[int, ...]:
    with closing(open_mbtiles(path)) as connection:
        try:
            rows = connection.execute("SELECT DISTINCT zoom_level FROM tiles ORDER BY zoom_level")
            zooms = tuple(zoom for (zoom,) in rows if type(zoom) is int and 0 <= zoom <= 30)
        except sqlite3.Error as exc:
            raise FetchError(f"Cannot read zoom levels from MBTiles archive {path}: {exc}") from exc
    if not zooms:
        raise FetchError(f"MBTiles archive contains no tiles at supported zoom levels: {path}")
    return zooms


def mbtiles_coverage(path: Path, tiles: TileRange) -> int:
    last_row = (1 << tiles.zoom) - 1
    with closing(open_mbtiles(path)) as connection:
        try:
            (count,) = connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT DISTINCT tile_column, tile_row FROM tiles
                    WHERE zoom_level = ? AND tile_column BETWEEN ? AND ?
                    AND tile_row BETWEEN ? AND ?
                )
                """,
                (tiles.zoom, tiles.x_min, tiles.x_max,
                 last_row - tiles.y_max, last_row - tiles.y_min),
            ).fetchone()
        except sqlite3.Error as exc:
            raise FetchError(f"Cannot check MBTiles coverage in {path}: {exc}") from exc
    return count


def _validate_url_template(template: str) -> None:
    try:
        fields = list(Formatter().parse(template))
    except ValueError as exc:
        raise ValidationError(f"Invalid custom URL template: {exc}") from exc
    placeholders = set()
    for _, field, spec, conversion in fields:
        if field is None:
            continue
        if field not in {"z", "source_z", "x", "y"} or spec or conversion:
            raise ValidationError(
                f"Unsupported placeholder in custom URL template: {{{field}}}. "
                "Use plain {z}, {x}, {y}, or {source_z} placeholders."
            )
        placeholders.add(field)
    if not {"z", "x", "y"} <= placeholders:
        raise ValidationError("Custom URL template must contain {z}, {x}, and {y} placeholders")


def resolve_source(
    source_id: str,
    *,
    custom_url_template: str | None = None,
    accept_custom_source_terms: bool = False,
    mbtiles_path: Path | None = None,
) -> MapSource:
    if mbtiles_path is not None:
        path = mbtiles_path.expanduser().resolve()
        if not path.is_file():
            raise ValidationError(f"MBTiles file does not exist: {path}")
        zooms = _mbtiles_zooms(path)
        return MapSource(
            id=f"mbtiles:{path.stem}",
            name=f"Local MBTiles: {path.name}",
            kind="mbtiles",
            tile_size=256,
            min_zoom=zooms[0],
            max_zoom=zooms[-1],
            url_template=None,
            preview_allowed=True,
            export_allowed=True,
            attribution="User-provided local archive",
            terms_url=None,
            coverage="Archive-defined",
            note="The user is responsible for the archive's license and attribution.",
            mbtiles_path=path,
            available_zooms=zooms,
        )

    if custom_url_template:
        _validate_url_template(custom_url_template)
        return MapSource(
            id="custom",
            name="Custom XYZ source",
            kind="xyz",
            tile_size=256,
            min_zoom=0,
            max_zoom=30,
            url_template=custom_url_template,
            preview_allowed=True,
            export_allowed=accept_custom_source_terms,
            attribution="User-provided source",
            terms_url=None,
            coverage="Source-defined",
            note=(
                "Export enabled by explicit user acknowledgement."
                if accept_custom_source_terms
                else "Use --accept-source-terms to confirm export rights."
            ),
        )

    try:
        return BUILTIN_SOURCES[source_id]
    except KeyError as exc:
        choices = ", ".join(sorted(BUILTIN_SOURCES))
        raise ValidationError(
            f"Unknown source '{source_id}'. Available: {choices}"
        ) from exc
