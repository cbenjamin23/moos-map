# MOOS Map

MOOS Map builds exact-crop TIFF background maps for MOOS-IvP. It has a
shared Python core, a command-line interface, and a local browser interface.
Both interfaces plan and build maps through the same source, geometry,
acquisition, raster, and MOOS compatibility modules.

The output bundle is intentionally small:

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

The UI opens on `http://127.0.0.1:8765`. Click and drag directly on the map to
select a region. Dragging again immediately replaces it. Source, zoom, and
selection changes update the summary automatically; there is no separate plan
step. Advanced MOOS origin controls live in the persistent Placement drawer.

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
  --zoom 20 \
  --source google-satellite
```

Build it:

```sh
moos-map build \
  --bounds -71.088 42.358 -71.087 42.359 \
  --origin 42.3585 -71.0875 \
  --zoom 20 \
  --source google-satellite \
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

## Exact cropping

Remote services divide imagery into 256-by-256-pixel source tiles. MOOS Map
downloads every tile touched by the requested rectangle, stitches them in
memory, and performs a fractional-pixel resample to the exact requested
bounds. The extra source-tile margins are discarded. The `.info` therefore
records the dragged or CLI-requested bounds exactly.

The summary estimates the residual placement error caused by pMarineViewer's
affine raster mapping. Current `BackImg` derives an unrotated rectangle from
diagonal UTM corner differences; exact cropping reduces the affected area but
does not rotate imagery into the UTM grid.

## Mission origin versus image center

The mission origin (`LatOrigin`/`LongOrigin`) is the geographic point that
MOOS calls local `(0, 0)`. It is not the center of the image. The image center
is simply halfway between the `.info` bounds and may have any local XY value.
MOOS Map writes the mission origin as `datum_lat`/`datum_lon`; it may be
outside the TIFF as long as it matches the mission configuration and remains
in the same UTM zone as the map.

## Sources and offline data

Built-in export sources:

- `google-satellite` — highest-detail default, confirmed through zoom 22 at MIT.
- `google-hybrid` — Google satellite imagery with labels, through zoom 22.
- `esri-world-imagery` — the satellite source used by Ray, through zoom 21 at MIT.
- `usgs-imagery` — U.S. orthoimagery, zoom 0–16.
- `usgs-topo` — U.S. topographic map, zoom 0–16.
- `osm-preview` — OpenStreetMap Standard, zoom 0–19.
- Local MBTiles archives supplied by the user.

The Google and Esri endpoints match the sources in Anaxi and Ray's prototype.
Native detail varies geographically. A custom XYZ source can be used with
`--url-template` after `--accept-source-terms` confirms access.

The tile cache is stored under `${XDG_CACHE_HOME:-~/.cache}/moos-map/tiles`.

## Current scope

- One active background bundle per build. Multiple-background orchestration is
  deferred while the upstream pMarineViewer texture allocation issue is fixed.
- Exact geographic crop is implemented; full UTM rotation/reprojection is not.
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
