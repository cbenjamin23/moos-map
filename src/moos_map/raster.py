from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from .errors import FetchError
from .models import PixelWindow, TileRange


def stitch_tiles(
    tile_data: dict[tuple[int, int], bytes],
    tiles: TileRange,
    tile_size: int,
) -> Image.Image:
    expected = set(tiles.coordinates())
    missing = expected.difference(tile_data)
    if missing:
        first = sorted(missing)[0]
        raise FetchError(f"Cannot stitch map; missing tile x={first[0]} y={first[1]}")

    output = Image.new("RGB", (tiles.columns * tile_size, tiles.rows * tile_size))
    for x, y in tiles.coordinates():
        with Image.open(BytesIO(tile_data[(x, y)])) as source_image:
            tile = source_image.convert("RGB")
            if tile.size != (tile_size, tile_size):
                raise FetchError(
                    f"Tile x={x} y={y} is {tile.width}x{tile.height}; "
                    f"expected {tile_size}x{tile_size}"
                )
            left = (x - tiles.x_min) * tile_size
            top = (y - tiles.y_min) * tile_size
            output.paste(tile, (left, top))
    return output


def crop_to_pixel_window(image: Image.Image, crop: PixelWindow) -> Image.Image:
    """Resample an exact fractional tile window into a tightly cropped raster."""

    return image.transform(
        (crop.output_width, crop.output_height),
        Image.Transform.EXTENT,
        data=(crop.left, crop.top, crop.right, crop.bottom),
        resample=Image.Resampling.BICUBIC,
    )


def save_tiff_atomic(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.", suffix=".tif", dir=destination.parent
    )
    os.close(handle)
    temporary_path = Path(temporary_name)
    try:
        image.save(
            temporary_path,
            format="TIFF",
            compression="tiff_lzw",
            dpi=(96, 96),
        )
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
