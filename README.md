# MOOS Map

MOOS Map builds exact-crop TIFF background maps for MOOS-IvP. It has a
shared Python core, a command-line interface, and a local browser interface.
Both interfaces plan and build maps through the same source, geometry,
acquisition, raster, and MOOS compatibility modules.

Each output bundle has its own map-name folder and remains intentionally small:

```text
~/moos-maps/harbor/
├── harbor.tif
├── harbor.info
└── harbor.moos
```

The `harbor.moos` copy-ready mission snippet is included by default and may be
disabled in either interface. No JSON sidecar is created. Source and
requested-bound provenance is stored as `//` comments in the `.info`, where
pMarineViewer safely ignores it.

To use a bundle, either copy its `.tif` and `.info` pair into the mission
directory or add that specific map folder to `IVP_IMAGE_DIRS`. pMarineViewer
does not recursively search the parent `~/moos-maps` directory.

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

The UI opens on `http://127.0.0.1:8765`. Click once to set the first corner,
move the pointer, and click the opposite corner to finish the region. A new
first click immediately starts replacing the prior selection. Click-hold-drag
pans the map; the wheel and map controls zoom it. Source, zoom, and selection
changes update the summary automatically; there is no separate plan step.
The collapsed section 04, Advanced placement, exposes editable map corners and
an optional existing-mission origin override. After selecting a region, drag
the red origin dot to set that origin visually. Export zoom defaults to 17 in
both the UI and CLI; it remains adjustable up to each source's limit.

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
  --zoom 17 \
  --source esri-world-imagery
```

Build it:

```sh
moos-map build \
  --bounds -71.088 42.358 -71.087 42.359 \
  --origin 42.3585 -71.0875 \
  --zoom 17 \
  --source esri-world-imagery \
  --name harbor \
  --output-dir ~/moos-maps
```

Same-name output bundles are replaced atomically by default. Use
`--no-overwrite` when an existing bundle must be protected. Use
`--refresh-tiles` only to bypass the local imagery cache and download fresh
source tiles. Use `--no-moos` to omit the default mission snippet.

Verify any same-basename TIFF/info pair:

```sh
moos-map verify ~/moos-maps/harbor/harbor.tif
```

Add `--json` to `sources`, `plan`, `build`, or `verify` for machine-readable
stdout. Progress remains on stderr.

## Exact cropping

Remote services divide imagery into 256-by-256-pixel source tiles. MOOS Map
downloads every tile touched by the requested rectangle, stitches them in
memory, and performs a fractional-pixel resample to the exact requested
bounds. The extra source-tile margins are discarded. The `.info` therefore
records the UI-selected or CLI-requested bounds exactly.

The summary includes a theoretical comparison between pMarineViewer's affine
raster placement and MOOS UTM coordinates. It is a model maximum, not a
measured image-registration error, and it does not imply that the bundled
MOOS-IvP or Anaxi maps are practically inaccurate. Any corrective reprojection
is deferred until the estimate has been checked against known landmarks and
real mission data.

## Mission origin versus image center

The mission origin (`LatOrigin`/`LongOrigin`) is the geographic point that
MOOS calls local `(0, 0)`. It is not the center of the image. The image center
is simply halfway between the `.info` bounds and may have any local XY value.
MOOS Map writes the mission origin as `datum_lat`/`datum_lon`; it may be
outside the TIFF as long as it matches the mission configuration and remains
in the same UTM zone as the map.

## Sources and offline data

Built-in sources:

- `esri-world-imagery` — default satellite source and the source used by Ray,
  through zoom 21 at MIT.
- `google-satellite` — high-detail satellite imagery, confirmed through zoom 22 at MIT.
- `google-hybrid` — Google satellite imagery with labels, through zoom 22.
- `google-maps` — detailed Google street map, through zoom 22 at MIT.
- `esri-world-topo` — detailed Esri topographic map, through zoom 19 at MIT.
- Local MBTiles archives supplied by the user.

The built-ins are the retained Google and Esri options from Anaxi and Ray's
prototype. Native detail varies geographically. A custom XYZ source can be
used with `--url-template` after `--accept-source-terms` confirms access.

Provider availability in the registry is not a grant of content-export rights.
Use Local MBTiles or a custom source with explicit static/offline permission for
a policy-defensible deployment; see the source provider's current terms before
exporting hosted imagery.

The tile cache is stored under `${XDG_CACHE_HOME:-~/.cache}/moos-map/tiles`.

## Current scope

- One active background bundle per build. Multiple-background orchestration is
  deferred while the upstream pMarineViewer texture allocation issue is fixed.
- Exact geographic crop is implemented; full UTM rotation/reprojection is not.
- Antimeridian and UTM-zone-crossing maps are rejected.
- TIFF and `.info` are required; `.moos` is generated by default and may be
  omitted.
- TIFF filenames use lowercase `.tif` and no whitespace.
- Coding-agent skill integration is the final roadmap phase, after the UI and
  CLI behavior settle.

See [docs/architecture.md](docs/architecture.md) for module boundaries and the
roadmap.

## Tests

```sh
python -m pytest
```

The test suite covers CLI defaults, tile rounding, placement metadata, source
policy, HTTP cache behavior, MBTiles Y-axis conversion, raster stitching,
bundle creation, exact on-disk size reporting, and the local API.

## License

No license has been selected yet.
