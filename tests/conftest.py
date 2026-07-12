from __future__ import annotations

from io import BytesIO

from PIL import Image


def make_tile(
    color: tuple[int, int, int], size: int = 256, format: str = "PNG"
) -> bytes:
    image = Image.new("RGB", (size, size), color)
    stream = BytesIO()
    image.save(stream, format=format)
    image.close()
    return stream.getvalue()
