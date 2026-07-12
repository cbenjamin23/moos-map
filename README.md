# MOOS Map

MOOS Map builds tile-aligned TIFF background maps for MOOS-IvP. It has a
shared Python core, a command-line interface, and a local browser interface.
Both interfaces plan and build maps through the same source, geometry,
acquisition, raster, and MOOS compatibility modules.

The v1 output is intentionally small:

```text
harbor.tif
harbor.info
```

An optional `harbor.moos` snippet can also be requested. No JSON sidecar is
created. Source and requested-bound provenance is stored as `//` comments in
the `.info`, where pMarineViewer safely ignores it.

## Install for development

MOOS Map requires Python 3.11 or newer.

```sh
cd ~/moos-map
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

## Local browser UI

```sh
moos-map ui
```

The UI opens on `http://127.0.0.1:8765`. Draw two opposite corners for the
requested map, place the mission origin, inspect the tile-aligned plan, and
then build the bundle.

## CLI

List the source registry:

```sh
moos-map sources
```

Inspect a plan without downloading:

```sh
moos-map plan \
  --bounds -71.088 42.358 -71.087 42.359 \
  --origin 42.3585 -71.0875 \
  --zoom 16 \
  --source usgs-imagery
```

Build it:

```sh
moos-map build \
  --bounds -71.088 42.358 -71.087 42.359 \
  --origin 42.3585 -71.0875 \
  --zoom 16 \
  --source usgs-imagery \
  --name harbor \
  --output-dir ~/moos-maps \
  --emit-moos
```

Verify any same-basename TIFF/info pair:

```sh
moos-map verify ~/moos-maps/harbor.tif
```

Add `--json` to `sources`, `plan`, `build`, or `verify` for machine-readable
stdout. Progress remains on stderr.

## How v1 chooses the image boundary

Remote tile services divide the map into 256-by-256-pixel image files. MOOS
Map selects every file touched by the requested rectangle, rounding outward,
and stitches those complete files together. The `.info` records the actual
outer tile boundaries, so no requested map content is cut off.

This is simpler and more reproducible than cropping. It can include more area
than requested, especially for very small requests; the plan reports that
expansion before downloading. It also estimates the vertical placement error
caused by displaying Web Mercator tile imagery with pMarineViewer's affine
raster mapping. Because current `BackImg` derives an unrotated rectangle from
diagonal UTM corner differences, the plan separately predicts the dimensions
pMarineViewer will use and sampled placement error both inside the requested
area and across the full rounded TIFF.

## Mission origin versus image center

The mission origin (`LatOrigin`/`LongOrigin`) is the geographic point that
MOOS calls local `(0, 0)`. It is not the center of the image. The image center
is simply halfway between the `.info` bounds and may have any local XY value.
MOOS Map writes the mission origin as `datum_lat`/`datum_lon`; it may be
outside the TIFF as long as it matches the mission configuration and remains
in the same UTM zone as the map.

## Sources and offline data

Built-in export sources:

- `usgs-imagery` — U.S. orthoimagery, zoom 0–16.
- `usgs-topo` — U.S. topographic map, zoom 0–16.
- Local MBTiles archives supplied by the user.

`osm-preview` is available for interactive context but the standard OSM tile
service is not enabled for static/offline export. A custom XYZ source can be
used with `--url-template` only after `--accept-source-terms` confirms that the
source permits the intended use.

The tile cache is stored under `${XDG_CACHE_HOME:-~/.cache}/moos-map/tiles`.

## Current scope

- One active background bundle per build. Multiple-background orchestration is
  deferred while the upstream pMarineViewer texture allocation issue is fixed.
- Whole XYZ tiles only; exact crop/reprojection is a later mode.
- Antimeridian and UTM-zone-crossing maps are rejected.
- TIFF and `.info` are required; `.moos` is optional.
- TIFF filenames use lowercase `.tif` and no whitespace.
- Coding-agent skill integration is the final roadmap phase, after the UI and
  CLI behavior settle.

See [docs/architecture.md](docs/architecture.md) for module boundaries and the
roadmap.

## Tests

```sh
python -m pytest
```

The test suite covers tile rounding, placement metadata, source policy, HTTP
cache behavior, MBTiles Y-axis conversion, raster stitching, bundle creation,
and the local API.

## License

No license has been selected yet.
