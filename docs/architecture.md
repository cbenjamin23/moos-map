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
  fractional-pixel crop windows, UTM checks, ground resolution, and
  pMarineViewer mapping-error estimation.
- `moos_compat.py`: a small, dependency-free replica of the current
  CMOOSGeodesy/BackImg UTM placement math used to predict viewer dimensions,
  local image center, and sampled affine placement error.
- `sources.py`: provider capabilities, policy, attribution, zoom bounds, and
  connection details.
- `acquisition.py`: validated HTTP and MBTiles tile readers.
- `cache.py`: atomic, source-isolated HTTP tile cache.
- `raster.py`: deterministic row-major tile stitching, exact fractional-pixel
  resampling, and atomic RGB TIFF output.
- `moos_files.py`: strict six-key `.info` parsing/writing and optional mission
  snippets.
- `verification.py`: independent bundle checks before returning success.
- `service.py`: planning/build orchestration and resource limits.
- `cli.py`: command-line adapter.
- `web.py` and `static/`: local HTTP adapter and manual UI.

## Compatibility contract

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

## Build sequence

1. Shared core and source registry.
2. CLI planning, building, and verification.
3. Local browser UI over the same core.
4. Compatibility and end-to-end validation with current MOOS-IvP.
5. Exact crop and curated high-detail Ray/Anaxi sources. (Complete in v0.3.)
6. Curated source cleanup and UI/CLI workflow polish. (Complete in v0.5.)
7. Multiple-background workflows after the pMarineViewer texture allocation
   defect is handled.
8. UTM background-display correction as the final compatibility milestone;
   navigation math is unaffected, but this is required before precision use.
9. Coding-agent skill, last, once the stable UI/CLI workflow is known.
