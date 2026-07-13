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
    url_zoom_offset: int = 0

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
    "google-terrain-hybrid": MapSource(
        id="google-terrain-hybrid",
        name="Google Terrain Hybrid",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=22,
        url_template="https://mt.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        preview_allowed=True,
        export_allowed=True,
        attribution="Google",
        terms_url="https://www.google.com/help/terms_maps/",
        coverage="Global",
        note="Terrain-oriented map with roads and labels. Detail varies by location.",
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
    "esri-world-street": MapSource(
        id="esri-world-street",
        name="Esri World Street Map",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=19,
        url_template=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
        ),
        preview_allowed=True,
        export_allowed=True,
        attribution="Esri, HERE, Garmin, and contributors",
        terms_url="https://www.esri.com/en-us/legal/terms/full-master-agreement",
        coverage="Global",
        note="Street map with roads, places, and local features. Native detail varies by location.",
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
    "esri-ocean": MapSource(
        id="esri-ocean",
        name="Esri Ocean / Bathymetry",
        kind="xyz",
        tile_size=256,
        min_zoom=0,
        max_zoom=16,
        url_template=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        preview_allowed=True,
        export_allowed=True,
        attribution="Esri, Garmin, GEBCO, NOAA, and contributors",
        terms_url="https://www.esri.com/en-us/legal/terms/full-master-agreement",
        coverage="Global",
        note="Ocean basemap with bathymetry and marine geographic context.",
    ),
    "noaa-chart-display": MapSource(
        id="noaa-chart-display",
        name="NOAA Nautical Charts",
        kind="xyz",
        tile_size=256,
        min_zoom=2,
        max_zoom=16,
        url_template=(
            "https://gis.charttools.noaa.gov/arcgis/rest/services/"
            "MarineChart_Services/NOAACharts/MapServer/tile/{source_z}/{y}/{x}"
        ),
        preview_allowed=True,
        export_allowed=True,
        attribution="NOAA Office of Coast Survey",
        terms_url="https://www.nauticalcharts.noaa.gov/data/gis-data-and-services.html",
        coverage="U.S. coastal waters and territories",
        note=(
            "Traditional chart portrayal derived from current NOAA ENC data. "
            "The online cache tops out at zoom 16; regional NOAA MBTiles may contain "
            "different zoom coverage. Not for navigation."
        ),
        url_zoom_offset=-2,
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
