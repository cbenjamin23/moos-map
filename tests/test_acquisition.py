from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
from PIL import Image

from conftest import make_tile
from moos_map.acquisition import HttpTileProvider, MBTilesProvider
from moos_map.cache import TileCache
from moos_map.sources import BUILTIN_SOURCES, resolve_source


def test_http_provider_validates_and_reuses_disk_cache(tmp_path: Path) -> None:
    source = replace(
        BUILTIN_SOURCES["usgs-imagery"],
        id="test-http",
        url_template="https://example.test/{z}/{x}/{y}.png",
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=make_tile((20, 40, 60)), request=request)

    provider = HttpTileProvider(source, cache=TileCache(source, tmp_path))
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        first = provider.fetch(3, 2, 1)
        second = provider.fetch(3, 2, 1)
    finally:
        provider.close()

    assert first == second
    assert calls == 1
    assert provider.downloaded_tiles == 1
    assert provider.cache_hits == 1


def test_mbtiles_provider_converts_xyz_y_to_tms_y(tmp_path: Path) -> None:
    archive = tmp_path / "chart.mbtiles"
    connection = sqlite3.connect(archive)
    connection.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
        "tile_row INTEGER, tile_data BLOB)"
    )
    xyz_y = 3
    tms_y = (1 << 3) - 1 - xyz_y
    connection.execute(
        "INSERT INTO tiles VALUES (?, ?, ?, ?)",
        (3, 2, tms_y, make_tile((90, 80, 70))),
    )
    connection.commit()
    connection.close()

    source = resolve_source("ignored", mbtiles_path=archive)
    provider = MBTilesProvider(source)
    try:
        data = provider.fetch(3, 2, xyz_y)
    finally:
        provider.close()

    with Image.open(__import__("io").BytesIO(data)) as image:
        assert image.getpixel((0, 0)) == (90, 80, 70)
