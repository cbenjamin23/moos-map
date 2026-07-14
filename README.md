# MOOS Map Builder

Build cropped TIFF background maps for MOOS-IvP through a local browser UI or
the `moos-map` command. Both interfaces use the same map sources, crop logic,
cache, and MOOS compatibility checks.

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

Esri World Imagery and zoom 17 are the defaults. The origin defaults to the
map center. For an existing mission, open **04 Advanced placement** and enter
its `LatOrigin` and `LongOrigin`, or drag the red origin dot.

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

The TIFF is cropped to the selected coordinates; extra downloaded tile margins
are discarded. Source and requested-bound provenance is kept as ignored `//`
comments in the `.info`; no JSON sidecar is created.

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
