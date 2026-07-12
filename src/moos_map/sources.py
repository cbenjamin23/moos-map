from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError


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

    def tile_url(self, zoom: int, x: int, y: int) -> str:
        if self.kind != "xyz" or not self.url_template:
            raise ValidationError(f"Source {self.id} does not provide XYZ URLs")
        return self.url_template.format(z=zoom, x=x, y=y)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["mbtiles_path"] = str(self.mbtiles_path) if self.mbtiles_path else None
        return result


BUILTIN_SOURCES: dict[str, MapSource] = {
    "usgs-imagery": MapSource(
        id="usgs-imagery",
        name="USGS Imagery",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=16,
        url_template=(
            "https://basemap.nationalmap.gov/arcgis/rest/services/"
            "USGSImageryOnly/MapServer/tile/{z}/{y}/{x}"
        ),
        preview_allowed=True,
        export_allowed=True,
        attribution="USGS The National Map / USDA",
        terms_url=(
            "https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-"
            "and-data-national-map"
        ),
        coverage="United States and territories",
        note="Cached orthoimagery; meaningful cached detail currently ends at zoom 16.",
    ),
    "usgs-topo": MapSource(
        id="usgs-topo",
        name="USGS Topographic Map",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=16,
        url_template=(
            "https://basemap.nationalmap.gov/arcgis/rest/services/"
            "USGSTopo/MapServer/tile/{z}/{y}/{x}"
        ),
        preview_allowed=True,
        export_allowed=True,
        attribution="USGS The National Map",
        terms_url=(
            "https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-"
            "and-data-national-map"
        ),
        coverage="United States and territories",
        note="Authoritative topographic basemap; meaningful cached detail ends at zoom 16.",
    ),
    "osm-preview": MapSource(
        id="osm-preview",
        name="OpenStreetMap (preview only)",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=19,
        url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        preview_allowed=True,
        export_allowed=False,
        attribution="OpenStreetMap contributors",
        terms_url="https://operations.osmfoundation.org/policies/tiles/",
        coverage="Global",
        note="The standard OSM tile service prohibits bulk/offline export.",
    ),
}


def list_sources() -> list[MapSource]:
    return list(BUILTIN_SOURCES.values())


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
        return MapSource(
            id=f"mbtiles:{path.stem}",
            name=f"Local MBTiles: {path.name}",
            kind="mbtiles",
            tile_size=256,
            min_zoom=0,
            max_zoom=30,
            url_template=None,
            preview_allowed=True,
            export_allowed=True,
            attribution="User-provided local archive",
            terms_url=None,
            coverage="Archive-defined",
            note="The user is responsible for the archive's license and attribution.",
            mbtiles_path=path,
        )

    if custom_url_template:
        required = ("{z}", "{x}", "{y}")
        if not all(token in custom_url_template for token in required):
            raise ValidationError(
                "Custom URL template must contain {z}, {x}, and {y} placeholders"
            )
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
