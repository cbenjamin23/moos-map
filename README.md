# MOOS Map Builder

Build cropped TIFF background maps for MOOS-IvP through a local browser UI or
the `moos-map` command. Both interfaces use the same map sources, crop logic,
cache, and MOOS compatibility checks.

MOOS Map targets current upstream MOOS-IvP with the default PROJ-backed
`CMOOSGeodesy`. Its datum-fixed UTM zone and hemisphere support maps that cross
zone boundaries or the equator. Legacy MOOS-IvP builds and current builds
configured with `--with-proj=off` are not supported for maps that cross a UTM
zone boundary or the equator.

[PyPI Project](https://pypi.org/project/moos-map/)

## Install

MOOS Map requires Python 3.11 or newer and [pipx](https://pipx.pypa.io/). On
macOS, install pipx and add its application directory to your shell path once:

```sh
brew install pipx
pipx ensurepath
```

Then install MOOS Map in its own managed environment:

```sh
pipx install moos-map
```

Then launch the UI:

```sh
moos-map ui
```

## UI

Click any two diagonally opposite corners to select a region. Click-hold-drag
pans the map; another single click starts a replacement selection. Review the
summary and choose **Build Map**.

Use **Find a place or enter lat, lon** above the map to move the preview to a
known location. Place-name autocomplete uses the public Photon service and
requires an internet connection; direct coordinates work locally. Search only
moves the preview viewport and never changes the selected export region,
mission origin, or export zoom.

Esri World Imagery and zoom 17 are the defaults. The origin defaults to the
map center. For an existing mission, open **04 Advanced placement** and enter
its `LatOrigin` and `LongOrigin`, or drag the red origin dot.

The browser app can start offline. Use **Local MBTiles archive** and enter the
corners under **Advanced placement** to build from local imagery. Press Enter
or leave a coordinate field to apply its edits. Select an
export zoom present in the archive. Hosted imagery and place-name search
require their respective services.

## CLI

Build with the same defaults by supplying any two diagonal corners as
`latitude longitude` pairs:

```sh
moos-map build \
  --corners 42.358 -71.088 42.359 -71.087 \
  --name harbor
```

For an existing mission, supply its origin:

```sh
moos-map build \
  --corners 42.358 -71.088 42.359 -71.087 \
  --origin 42.358436 -71.087448 \
  --name harbor
```

Useful commands:

```sh
moos-map sources
moos-map plan --corners 42.358 -71.088 42.359 -71.087
moos-map verify ~/moos-maps/harbor/harbor.tif
moos-map build -h
```

`build` downloads immediately; running `sources` or `plan` first is optional.
Use `--zoom`, `--source`, or `--output-dir` to override defaults. Builds include
a `.moos` snippet and replace same-named bundles safely by default. See
`moos-map build -h` for opt-out and cache controls.

Planning warns when a TIFF side exceeds the pMarineViewer texture target and
suggests a lower zoom when one fits. Set the target per side with
`--max-texture-dimension` or in the browser's advanced placement settings.
The default is 16,384 pixels. The target only affects the warning.

Split a selection that crosses the date line into two exports, one bounded by
`180` and the other by `-180`. Use `--allow-wide-bounds` when you intend to cover
more than 180 degrees between the numerically ordered longitudes.

## Output

Each map gets its own directory:

```text
~/moos-maps/harbor/
├── harbor.tif
├── harbor.info
└── harbor.moos
```

Copy the `.tif` and `.info` files into a mission directory, or add that exact
map directory to `IVP_IMAGE_DIRS`. Then add the generated `harbor.moos` settings
to the mission. pMarineViewer does not recursively search `~/moos-maps`.

When a rebuild omits the mission snippet, MOOS Map removes an existing snippet
that exactly matches the one generated for the previous map. It preserves edited
or unrecognized snippets and asks you to check their mission settings.
For a same-name rebuild that generates a snippet, existing edited or unrecognized
mission files stop the rebuild. Choose a different name or omit the snippet.
If a process stops during final installation, `verify` reports an incomplete
bundle. Rebuild the same map to restore the previous files before installing
the new export.

The TIFF is cropped to the selected coordinates; extra downloaded tile margins
are discarded. Source and requested-bound provenance is kept as ignored `//`
comments in the `.info`; no JSON sidecar is created.

New exports carry a matching identifier in the TIFF and `.info`. `verify`
checks that the files are from the same export and that the placement metadata
matches. Existing TIFFs and `.info` files can still be verified. Regenerate a
bound pair when changing its bounds or mission origin.
`verify` also warns if a same-name generated `.moos` snippet disagrees with the
map's origin or TIFF name.

Near the date line, `.info` may use an equivalent longitude adjacent to the
image for pMarineViewer placement. Use the generated `.moos` snippet for the
mission's canonical `LongOrigin`.

## Sources

Built-ins include Esri World Imagery, Google Satellite, Google Hybrid, Google
Maps, and Esri World Topographic. Local MBTiles and custom XYZ services are
also supported. Native detail varies by location. A listed provider is not a
grant of export rights; check its current terms before downloading hosted
imagery.

The tile cache is `${XDG_CACHE_HOME:-~/.cache}/moos-map/tiles`.

## Development

```sh
git clone https://github.com/cbenjamin23/moos-map.git
cd moos-map
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
```

See [docs/architecture.md](docs/architecture.md) for module boundaries,
[docs/validation.md](docs/validation.md) for the MIT pMarineViewer comparison,
and [TODO.md](TODO.md) for deferred work.

## License

GPL-3.0-only. See [LICENSE](LICENSE).

## Acknowledgements

MOOS Map grew out of earlier map-building work in the MOOS-IvP community. We
are grateful to:

- **HeroCC/AnaxiMap:** [HeroCC/AnaxiMap](https://github.com/HeroCC/AnaxiMap)
  demonstrated a practical tile-download and stitching workflow that inspired
  MOOS Map's map acquisition pipeline.
- **Raymond Turrisi:** His map-building prototype helped shape the practical
  workflow and direction of this project.

AnaxiMap already provided coordinate-driven XYZ tile acquisition and stitching,
source selection, downloaded-tile reuse, and initial `.info` generation. Ray's
prototype already provided browser map navigation, two-click region selection,
adjustable bounds and origin, location search, live export estimates, imagery
selection, and TIFF export. MOOS Map independently implemented and extended
those foundations with:

- **Exact Geographic Cropping:** Resamples the fractional source-tile window so
  the TIFF and its recorded bounds match the requested coordinates instead of
  retaining whole-tile margins.

- **pMarineViewer Metadata:** Produces the strict six-key `.info` format expected
  by current `pMarineViewer`, including the mission datum. Ray's prototype does
  not generate `.info`; AnaxiMap's file includes additional active keys that
  current `pMarineViewer` rejects.

- **Complete Map Bundles:** Places matching `.tif`, `.info`, and optional
  copy-ready `.moos` files together in a named output directory.

- **Current MOOS Geodesy Compatibility:** Supports datum-fixed PROJ maps that
  cross UTM boundaries or the equator and calculates pMarineViewer placement
  estimates even when the map center and mission origin select different
  natural zones.

- **Shared CLI and GUI Core:** Uses the same source registry, crop calculations,
  cache, output writers, and validation from both interfaces, rather than
  maintaining separate build implementations.

- **Reproducible Planning:** Extends AnaxiMap's dry run and Ray's live estimates
  with exact output dimensions, tile and pixel counts, resolution, ground size,
  selected bounds, mission origin, and modeled `pMarineViewer` placement.

- **Post-Build Verification:** Reopens completed TIFF and `.info` files and
  verifies their dimensions, names, bounds, datum, syntax, and bundle
  consistency before reporting success.

- **Reliable Tile Acquisition:** Downloads concurrently, retries throttling and
  transient server errors, validates returned image data and dimensions, and
  rejects incomplete builds.

- **Source-Isolated Caching:** Stores reusable tiles in provider-specific
  namespaces, preventing imagery from different services at the same
  coordinates from colliding.

- **Offline MBTiles Support:** Builds maps directly from local MBTiles archives
  without contacting a hosted tile provider.

- **Source Policy Controls:** Records attribution and provider metadata,
  distinguishes preview-only sources, and requires explicit acknowledgement
  before exporting from a custom XYZ service.

- **Bounded Builds:** Enforces configurable tile-count, pixel-count,
  response-size, coordinate, and zoom limits before expensive or unsafe work
  begins.

- **Transaction-Safe Output:** Builds and verifies files in staging, serializes
  installations targeting the same bundle, and restores prior files if
  installation or verification fails.

- **Automation Interfaces:** Provides `sources`, `plan`, `build`, and `verify`
  commands with machine-readable JSON output for repeatable scripts and agent
  workflows.

- **Improved Place Search:** Extends Ray's single-result, submit-only Nominatim
  search with autocomplete, multiple ranked results, duplicate removal,
  keyboard navigation, result-specific viewport fitting, server-side Photon
  requests, caching, and structured error handling.

- **Automated Tests:** Covers geometry, acquisition, caching, source policy,
  bundle generation, `.info` parsing, CLI behavior, web endpoints, geocoding,
  and failure recovery.

- **Viewer Validation:** Documents a direct comparison with the shipped MIT
  `pMarineViewer` map using matched local and geographic vehicle positions to
  validate TIFF alignment, datum handling, and mission placement.
