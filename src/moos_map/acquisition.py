from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from io import BytesIO
from typing import Callable, Protocol

import httpx
from PIL import Image, UnidentifiedImageError

from . import __version__
from .cache import TileCache
from .errors import FetchError
from .models import TileRange
from .sources import MapSource


ProgressCallback = Callable[[int, int, int, int], None]


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
            cached = self.cache.read(zoom, x, y)
            if cached is not None:
                try:
                    validate_tile_bytes(cached, self.source.tile_size, description)
                except FetchError:
                    self.cache.path_for(zoom, x, y).unlink(missing_ok=True)
                else:
                    with self._stats_lock:
                        self.cache_hits += 1
                    return cached

        url = self.source.tile_url(zoom, x, y)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self._client.get(url)
                if response.status_code == 200:
                    data = response.content
                    if len(data) > 10 * 1024 * 1024:
                        raise FetchError(
                            f"Tile response exceeded 10 MB for {description}"
                        )
                    validate_tile_bytes(data, self.source.tile_size, description)
                    self.cache.write(zoom, x, y, data)
                    with self._stats_lock:
                        self.downloaded_tiles += 1
                    return data

                message = f"HTTP {response.status_code} fetching {description}"
                if response.status_code not in self.RETRYABLE_STATUS_CODES:
                    raise FetchError(message)

                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = min(float(retry_after), 10.0)
                except ValueError:
                    delay = min(0.5 * (2**attempt), 8.0)
                last_error = FetchError(message)
            except (httpx.HTTPError, FetchError) as exc:
                last_error = exc
                if isinstance(exc, FetchError) and "HTTP " in str(exc):
                    status_text = str(exc).split("HTTP ", 1)[1].split(" ", 1)[0]
                    if (
                        status_text.isdigit()
                        and int(status_text) not in self.RETRYABLE_STATUS_CODES
                    ):
                        raise
                delay = min(0.5 * (2**attempt), 8.0)

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
        try:
            self._connection = sqlite3.connect(self.path, check_same_thread=False)
            self._connection.execute("SELECT 1 FROM tiles LIMIT 1")
        except sqlite3.Error as exc:
            raise FetchError(f"Invalid MBTiles archive: {self.path}") from exc

    def fetch(self, zoom: int, x: int, y: int, *, force: bool = False) -> bytes:
        del force
        tms_y = (1 << zoom) - 1 - y
        with self._lock:
            row = self._connection.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (zoom, x, tms_y),
            ).fetchone()
        if row is None:
            raise FetchError(
                f"Tile is absent from {self.path.name}: z={zoom} x={x} y={y}"
            )
        data = bytes(row[0])
        validate_tile_bytes(
            data, self.source.tile_size, f"{self.path.name} z={zoom} x={x} y={y}"
        )
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
