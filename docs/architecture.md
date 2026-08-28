# Architecture

The interfaces are deliberately thin. `cli.py` and `web.py` translate user
input into a `MapRequest`; all map behavior lives below them.

```text
CLI ─┐
     ├─> service ─> geometry
UI  ─┘           ├> source registry
                 ├> acquisition/cache
                 ├> raster assembly
                 ├> MOOS file writer
                 └> verification
```

## Modules

- `models.py`: immutable request, bounds, tile range, plan, and result types.
- `geometry.py`: XYZ/Web Mercator math, intersecting-tile selection,
  fractional-pixel crop windows, UTM zone selection, ground resolution, and
  pMarineViewer mapping-error estimation.
- `moos_compat.py`: a small, dependency-free replica of current PROJ-backed
  CMOOSGeodesy datum-fixed projection and BackImg placement math used to predict
  viewer dimensions, local image center, and sampled affine placement error.
- `sources.py`: provider capabilities, policy, attribution, zoom bounds, and
  connection details.
- `geocoding.py`: Photon place-search adapter, provider-neutral result
  normalization, short-lived query cache, and remote failure handling.
- `acquisition.py`: validated HTTP and MBTiles tile readers.
- `cache.py`: atomic, source-isolated HTTP tile cache.
- `raster.py`: deterministic row-major tile stitching, exact fractional-pixel
  resampling, and atomic RGB TIFF output.
- `moos_files.py`: strict six-key `.info` parsing/writing and default,
  opt-out mission snippets.
- `verification.py`: independent bundle checks before returning success.
- `service.py`: planning/build orchestration and resource limits.
- `cli.py`: command-line adapter.
- `web.py` and `static/`: local HTTP adapter and manual UI.

## Compatibility contract

MOOS Map targets current upstream MOOS-IvP with its default PROJ-backed
CMOOSGeodesy. Bounds may cross UTM zone boundaries or the equator because each
local frame retains the zone and hemisphere selected by its datum. The legacy
handwritten backend selected with `--with-proj=off` is not a zone- or
equator-crossing compatibility target.

A boundary crossing is not itself a placement warning. The theoretical affine
placement estimate applies to every map and remains available independently of
whether its bounds cross a UTM boundary.

The map-center and mission-origin zones do not need to match. BackImg uses the
map-center projection only to size its axis-aligned rectangle and anchors that
rectangle at the mission datum, while mission coordinates use the origin's
projection. Different natural zones therefore change projection scale and axis
orientation rather than introducing the legacy UTM easting jump. The ordinary
placement estimate models this case just as it does for every other map.

The generated TIFF and info file must share a basename. The `.info` contains
exactly these active keys:

```text
lat_north
lat_south
lon_east
lon_west
datum_lat
datum_lon
```

All provenance is commented with `//`. This follows the current pMarineViewer
loader, which rejects unknown active `.info` keys and does not use GeoTIFF
georeferencing tags in place of the sidecar.

Each build is placed in its own map-name directory. The default bundle contains
the required same-basename `.tif`/`.info` pair and a copy-ready `.moos` mission
snippet; either interface may omit the snippet.

Deferred work is tracked in [TODO.md](../TODO.md).
