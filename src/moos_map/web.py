from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .errors import MoosMapError
from .models import Bounds, MapRequest, Origin
from .service import build_map, plan_map
from .sources import list_sources
from .verification import verify_bundle


STATIC_DIR = Path(__file__).with_name("static")


class BoundsPayload(BaseModel):
    west: float
    south: float
    east: float
    north: float


class OriginPayload(BaseModel):
    latitude: float
    longitude: float


class MapPayload(BaseModel):
    bounds: BoundsPayload
    origin: OriginPayload
    zoom: int = Field(default=17, ge=0, le=30)
    source_id: str = "google-satellite"
    name: str = "moos_map"
    output_dir: str = "~/moos-maps"
    emit_moos: bool = False
    force: bool = False
    overwrite: bool = True
    refresh_tiles: bool = False
    custom_url_template: str | None = None
    accept_custom_source_terms: bool = False
    mbtiles_path: str | None = None
    max_tiles: int = Field(default=1024, ge=1)
    max_pixels: int = Field(default=67_108_864, ge=65_536)

    def to_request(self) -> MapRequest:
        return MapRequest(
            bounds=Bounds(**self.bounds.model_dump()),
            origin=Origin(**self.origin.model_dump()),
            zoom=self.zoom,
            source_id=self.source_id,
            name=self.name,
            output_dir=Path(self.output_dir),
            emit_moos=self.emit_moos,
            force=self.force,
            overwrite=self.overwrite,
            refresh_tiles=self.refresh_tiles,
            custom_url_template=self.custom_url_template or None,
            accept_custom_source_terms=self.accept_custom_source_terms,
            mbtiles_path=Path(self.mbtiles_path) if self.mbtiles_path else None,
            max_tiles=self.max_tiles,
            max_pixels=self.max_pixels,
        )


class VerifyPayload(BaseModel):
    tiff_path: str


def create_app() -> FastAPI:
    app = FastAPI(title="MOOS Map", version=__version__, docs_url="/api/docs")

    @app.exception_handler(MoosMapError)
    async def handle_moos_map_error(
        request: Request, exc: MoosMapError
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/sources")
    def sources() -> dict[str, Any]:
        return {"sources": [source.as_dict() for source in list_sources()]}

    @app.post("/api/plan")
    def plan(payload: MapPayload) -> dict[str, Any]:
        return plan_map(payload.to_request()).as_dict()

    @app.post("/api/build")
    def build(payload: MapPayload) -> dict[str, Any]:
        return build_map(payload.to_request()).as_dict()

    @app.post("/api/verify")
    def verify(payload: VerifyPayload) -> dict[str, Any]:
        return verify_bundle(Path(payload.tiff_path)).as_dict()

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()


def run_ui(*, host: str, port: int, open_browser: bool = True) -> None:
    url = f"http://{host}:{port}"
    if open_browser:
        timer = threading.Timer(0.8, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host=host, port=port, log_level="info")
