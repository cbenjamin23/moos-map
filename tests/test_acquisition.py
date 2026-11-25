from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from conftest import make_tile
from moos_map.acquisition import MAX_TILE_BYTES, HttpTileProvider, MBTilesProvider
from moos_map.cache import TileCache
from moos_map.errors import FetchError
from moos_map.sources import BUILTIN_SOURCES, resolve_source


def test_http_provider_validates_and_reuses_disk_cache(tmp_path: Path) -> None:
    source = replace(
        BUILTIN_SOURCES["google-satellite"],
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


@pytest.mark.parametrize("cache_entry", ["corrupt image", "directory", "unwritable"])
def test_http_provider_uses_valid_download_when_cache_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache_entry: str
) -> None:
    source = replace(
        BUILTIN_SOURCES["google-satellite"],
        id="test-http",
        url_template="https://example.test/{z}/{x}/{y}.png",
    )
    cache = TileCache(source, tmp_path)
    if cache_entry == "corrupt image":
        cache.write(3, 2, 1, b"invalid tile")
    elif cache_entry == "directory":
        cache.path_for(3, 2, 1).mkdir(parents=True)
    else:
        def reject_write(*args: object) -> None:
            raise PermissionError("read-only cache")

        monkeypatch.setattr(cache, "write", reject_write)

    tile = make_tile((20, 40, 60))
    provider = HttpTileProvider(source, cache=cache, retries=0)
    provider._client.close()
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=tile))
    provider._client = httpx.Client(transport=transport)
    try:
        assert provider.fetch(3, 2, 1) == tile
    finally:
        provider.close()

    assert provider.downloaded_tiles == 1
    assert provider.cache_hits == 0
    if cache_entry == "corrupt image":
        assert cache.read(3, 2, 1) == tile


@pytest.mark.parametrize("relation", ["table", "view"])
def test_mbtiles_provider_converts_xyz_y_to_tms_y(tmp_path: Path, relation: str) -> None:
    archive = tmp_path / "chart.mbtiles"
    table = "stored_tiles" if relation == "view" else "tiles"
    connection = sqlite3.connect(archive)
    connection.execute(
        f"CREATE TABLE {table} (zoom_level INTEGER, tile_column INTEGER, "
        "tile_row INTEGER, tile_data BLOB)"
    )
    if relation == "view":
        connection.execute("CREATE VIEW tiles AS SELECT * FROM stored_tiles")
    xyz_y = 3
    tms_y = (1 << 3) - 1 - xyz_y
    connection.execute(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?)",
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

    with Image.open(BytesIO(data)) as image:
        assert image.getpixel((0, 0)) == (90, 80, 70)


def test_mbtiles_provider_rejects_an_incomplete_schema(tmp_path: Path) -> None:
    archive = tmp_path / "missing-data-column.mbtiles"
    with closing(sqlite3.connect(archive)) as connection:
        connection.execute(
            "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER)"
        )

    with pytest.raises(FetchError, match="Invalid MBTiles archive.*tile_data"):
        resolve_source("ignored", mbtiles_path=archive)


def test_mbtiles_provider_reports_invalid_tile_data_and_failed_reads(tmp_path: Path) -> None:
    archive = tmp_path / "broken-tile.mbtiles"
    with closing(sqlite3.connect(archive)) as connection:
        connection.execute(
            "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
            "tile_row INTEGER, tile_data BLOB)"
        )
        connection.execute("INSERT INTO tiles VALUES (0, 0, 0, NULL)")
        connection.commit()

        provider = MBTilesProvider(resolve_source("ignored", mbtiles_path=archive))
        try:
            with pytest.raises(FetchError, match="Invalid MBTiles tile data.*expected a BLOB"):
                provider.fetch(0, 0, 0)
            connection.execute("DROP TABLE tiles")
            with pytest.raises(FetchError, match="Could not read tile.*no such table"):
                provider.fetch(0, 0, 0)
        finally:
            provider.close()


@pytest.mark.parametrize(("header", "delay"), [
    ("-1", 0.5), ("NaN", 0.5), ("2", 2.0), ("Thu, 01 Jan 1970 00:00:08 GMT", 8.0),
])
def test_http_provider_retries_with_a_valid_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, header: str, delay: float
) -> None:
    sleep = Mock()
    monkeypatch.setattr("moos_map.acquisition.time.sleep", sleep)
    monkeypatch.setattr("moos_map.acquisition.time.time", lambda: 0)
    tile = make_tile((20, 40, 60))
    responses = iter([
        httpx.Response(503, headers={"Retry-After": header}),
        httpx.Response(200, content=tile),
    ])
    source = BUILTIN_SOURCES["google-satellite"]
    provider = HttpTileProvider(source, cache=TileCache(source, tmp_path), retries=1)
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(lambda _: next(responses)))
    try:
        assert provider.fetch(3, 2, 1) == tile
        sleep.assert_called_once_with(delay)
    finally:
        provider.close()


def test_http_provider_stops_reading_an_oversized_tile(tmp_path: Path) -> None:
    class OversizedTile(httpx.SyncByteStream):
        chunks_read = 0

        def __iter__(self):
            chunk = bytes(MAX_TILE_BYTES // 10)
            for _ in range(12):
                self.chunks_read += 1
                yield chunk

    stream = OversizedTile()
    source = BUILTIN_SOURCES["google-satellite"]
    provider = HttpTileProvider(source, cache=TileCache(source, tmp_path))
    provider._client.close()
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    provider._client = httpx.Client(transport=transport)
    try:
        with pytest.raises(FetchError, match="exceeded 10 MiB"):
            provider.fetch(3, 2, 1)
        assert stream.chunks_read == 11
        assert provider.cache.read(3, 2, 1) is None
    finally:
        provider.close()
