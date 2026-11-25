from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import suppress
from datetime import timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Callable, Protocol

import httpx
from PIL import Image, UnidentifiedImageError

from . import __version__
from .cache import TileCache
from .errors import FetchError
from .models import TileRange
from .sources import MapSource, open_mbtiles


ProgressCallback = Callable[[int, int, int, int], None]
MAX_TILE_BYTES = 10 * 1024 * 1024


class TileProvider(Protocol):
    cache_hits: int
    downloaded_tiles: int

    def fetch(self, zoom: int, x: int, y: int, *, force: bool = False) -> bytes: ...

    def close(self) -> None: ...


def validate_tile_bytes(data: bytes, tile_size: int, description: str) -> None:
    if not data:
        raise FetchError(f"Empty tile response for {description}")
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.size != (tile_size, tile_size):
                raise FetchError(
                    f"Unexpected tile dimensions for {description}: "
                    f"{image.width}x{image.height}, expected {tile_size}x{tile_size}"
                )
    except (UnidentifiedImageError, OSError) as exc:
        raise FetchError(
            f"Response was not a readable image for {description}"
        ) from exc


def _read_tile(response: httpx.Response, description: str) -> bytes:
    data = bytearray()
    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        if len(data) + len(chunk) > MAX_TILE_BYTES:
            raise FetchError(f"Tile response exceeded 10 MiB for {description}")
        data.extend(chunk)
    return bytes(data)


def _retry_delay(header: str, fallback: float) -> float:
    try:
        if header.isascii() and header.isdecimal():
            return min(int(header), 10)
        retry_at = parsedate_to_datetime(header)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return min(max(retry_at.timestamp() - time.time(), 0), 10)
    except (ValueError, TypeError, OverflowError, OSError):
        return fallback


class HttpTileProvider:
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        source: MapSource,
        *,
        cache: TileCache | None = None,
        timeout_seconds: float = 20.0,
        retries: int = 3,
    ) -> None:
        self.source = source
        self.cache = cache or TileCache(source)
        self.retries = retries
        self.cache_hits = 0
        self.downloaded_tiles = 0
        self._stats_lock = threading.Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={
                "User-Agent": f"moos-map/{__version__} (+local MOOS-IvP map builder)",
                "Accept": "image/*",
            },
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )

    def fetch(self, zoom: int, x: int, y: int, *, force: bool = False) -> bytes:
        description = f"{self.source.id} z={zoom} x={x} y={y}"
        if not force:
            try:
                cached = self.cache.read(zoom, x, y)
                if cached is not None:
                    validate_tile_bytes(cached, self.source.tile_size, description)
            except (OSError, FetchError):
                cached = None
            if cached is not None:
                with self._stats_lock:
                    self.cache_hits += 1
                return cached

        url = self.source.tile_url(zoom, x, y)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            delay = min(0.5 * (2**attempt), 8.0)
            try:
                with self._client.stream("GET", url) as response:
                    if response.status_code == 200:
                        data = _read_tile(response, description)
                        try:
                            validate_tile_bytes(data, self.source.tile_size, description)
                        except FetchError as exc:
                            last_error = exc
                        else:
                            # Cache writes are optional once the tile is validated.
                            with suppress(OSError):
                                self.cache.write(zoom, x, y, data)
                            with self._stats_lock:
                                self.downloaded_tiles += 1
                            return data
                    else:
                        error = FetchError(f"HTTP {response.status_code} fetching {description}")
                        if response.status_code not in self.RETRYABLE_STATUS_CODES:
                            raise error
                        last_error = error
                        delay = _retry_delay(response.headers.get("Retry-After", ""), delay)
            except httpx.HTTPError as exc:
                last_error = exc

            if attempt < self.retries:
                time.sleep(delay)

        raise FetchError(
            f"Failed after {self.retries + 1} attempts: {description}"
        ) from last_error

    def close(self) -> None:
        self._client.close()


class MBTilesProvider:
    def __init__(self, source: MapSource) -> None:
        if not source.mbtiles_path:
            raise FetchError("MBTiles source has no archive path")
        self.source = source
        self.path = source.mbtiles_path
        self.cache_hits = 0
        self.downloaded_tiles = 0
        self._lock = threading.Lock()
        self._connection = open_mbtiles(self.path, check_same_thread=False)

    def fetch(self, zoom: int, x: int, y: int, *, force: bool = False) -> bytes:
        del force
        tms_y = (1 << zoom) - 1 - y
        description = f"{self.path.name}: z={zoom} x={x} y={y}"
        try:
            with self._lock:
                row = self._connection.execute(
                    "SELECT tile_data FROM tiles "
                    "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                    (zoom, x, tms_y),
                ).fetchone()
        except sqlite3.Error as exc:
            raise FetchError(f"Could not read tile from {description}: {exc}") from exc
        if row is None:
            raise FetchError(f"Tile is absent from {description}")
        data = row[0]
        if not isinstance(data, bytes):
            raise FetchError(f"Invalid MBTiles tile data for {description}: expected a BLOB")
        validate_tile_bytes(data, self.source.tile_size, description)
        with self._lock:
            self.cache_hits += 1
        return data

    def close(self) -> None:
        self._connection.close()


def create_provider(source: MapSource) -> TileProvider:
    if source.kind == "xyz":
        return HttpTileProvider(source)
    if source.kind == "mbtiles":
        return MBTilesProvider(source)
    raise FetchError(f"Unsupported source kind: {source.kind}")


def fetch_tile_range(
    provider: TileProvider,
    tiles: TileRange,
    *,
    force: bool = False,
    workers: int = 4,
    progress: ProgressCallback | None = None,
) -> dict[tuple[int, int], bytes]:
    coordinates = list(tiles.coordinates())
    results: dict[tuple[int, int], bytes] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as executor:
        futures: dict[Future[bytes], tuple[int, int]] = {
            executor.submit(provider.fetch, tiles.zoom, x, y, force=force): (x, y)
            for x, y in coordinates
        }
        try:
            for future in as_completed(futures):
                x, y = futures[future]
                results[(x, y)] = future.result()
                completed += 1
                if progress:
                    progress(completed, len(coordinates), x, y)
        except Exception:
            for future in futures:
                future.cancel()
            raise

    return results
