from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from .sources import MapSource


def default_cache_dir() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "moos-map" / "tiles"


def source_cache_namespace(source: MapSource) -> str:
    identity = source.url_template or str(source.mbtiles_path or source.id)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", source.id)
    return f"{safe_id}-{digest}"


class TileCache:
    def __init__(self, source: MapSource, root: Path | None = None) -> None:
        self.root = (root or default_cache_dir()).expanduser()
        self.namespace = source_cache_namespace(source)

    def path_for(self, zoom: int, x: int, y: int) -> Path:
        return self.root / self.namespace / str(zoom) / str(x) / f"{y}.tile"

    def read(self, zoom: int, x: int, y: int) -> bytes | None:
        path = self.path_for(zoom, x, y)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def write(self, zoom: int, x: int, y: int, data: bytes) -> Path:
        path = self.path_for(zoom, x, y)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
        return path
