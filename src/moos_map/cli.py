from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .errors import MoosMapError
from .models import Bounds, MapRequest, Origin
from .service import build_map, plan_map
from .sources import list_sources
from .verification import verify_bundle


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _add_machine_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )


def _add_map_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bounds",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        required=True,
        help=(
            "Two opposite WGS84 corners expressed as west south east north "
            "(bottom-left longitude/latitude, then top-right longitude/latitude)"
        ),
    )
    parser.add_argument(
        "--origin",
        nargs=2,
        type=float,
        metavar=("LAT", "LON"),
        required=True,
        help="MOOS LatOrigin and LongOrigin",
    )
    parser.add_argument(
        "--zoom", type=int, default=17, help="XYZ zoom level (default: 17)"
    )
    parser.add_argument(
        "--source",
        default="esri-world-imagery",
        help="Built-in source ID (default: esri-world-imagery)",
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--url-template",
        help="Custom XYZ URL containing {z}, {x}, and {y}",
    )
    source_group.add_argument(
        "--mbtiles",
        type=Path,
        help="Read tiles from a local MBTiles archive",
    )
    parser.add_argument(
        "--accept-source-terms",
        action="store_true",
        help="Confirm that a custom source permits static/offline export",
    )
    parser.add_argument("--max-tiles", type=int, default=1024)
    parser.add_argument("--max-pixels", type=int, default=67_108_864)


def _request_from_args(args: argparse.Namespace) -> MapRequest:
    west, south, east, north = args.bounds
    latitude, longitude = args.origin
    return MapRequest(
        bounds=Bounds(west=west, south=south, east=east, north=north),
        origin=Origin(latitude=latitude, longitude=longitude),
        zoom=args.zoom,
        source_id=args.source,
        name=getattr(args, "name", "moos_map"),
        output_dir=getattr(args, "output_dir", Path.home() / "moos-maps"),
        emit_moos=getattr(args, "emit_moos", True),
        force=getattr(args, "force", False),
        overwrite=getattr(args, "overwrite", True),
        refresh_tiles=getattr(args, "refresh_tiles", False),
        custom_url_template=args.url_template,
        accept_custom_source_terms=args.accept_source_terms,
        mbtiles_path=args.mbtiles,
        max_tiles=args.max_tiles,
        max_pixels=args.max_pixels,
    )


def _format_file_size(size_bytes: int, *, precise: bool = False) -> str:
    if size_bytes < 1_000:
        return f"{size_bytes:,} bytes"
    if size_bytes < 1_000_000:
        return f"{size_bytes / 1_000:.{1 if precise else 0}f} KB"
    return f"{size_bytes / 1_000_000:.{2 if precise else 1}f} MB"


def _print_plan_human(
    plan: dict[str, Any], *, actual_tiff_size_bytes: int | None = None
) -> None:
    source = plan["source"]
    tiles = plan["tiles"]
    actual = plan["actual_bounds"]
    origin = plan["origin"]
    print(f"Source: {source['name']} ({source['id']})")
    print(
        f"Source tiles: {tiles['count']} "
        f"({tiles['columns']} x {tiles['rows']}), zoom {tiles['zoom']}"
    )
    print(f"TIFF dimensions: {plan['pixel_width']} x {plan['pixel_height']} pixels")
    if actual_tiff_size_bytes is None:
        print(
            "Estimated TIFF size: "
            f"~{_format_file_size(plan['estimated_tiff_size_bytes'])} "
            "before content-dependent LZW compression"
        )
    else:
        print(
            "TIFF file size: "
            f"{_format_file_size(actual_tiff_size_bytes, precise=True)} "
            f"({actual_tiff_size_bytes:,} bytes)"
        )
    print(
        "Exact bounds: "
        f"W {actual['west']:.10f}, S {actual['south']:.10f}, "
        f"E {actual['east']:.10f}, N {actual['north']:.10f}"
    )
    print(
        "Mission origin: "
        f"LatOrigin {origin['latitude']:.10f}, "
        f"LongOrigin {origin['longitude']:.10f}"
    )
    print(
        "Ground area: "
        f"{plan['approximate_ground_width_m']:.1f} x "
        f"{plan['approximate_ground_height_m']:.1f} m"
    )
    print(f"Source resolution: {plan['approximate_meters_per_pixel']:.3f} m/pixel")
    print(
        "Display alignment: "
        f"{plan['estimated_max_requested_area_position_error_m']:.1f} m model max "
        "(theoretical, not measured)"
    )
    print("Output crop: exact requested bounds")
    for warning in plan["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moos-map",
        description="Build exact-crop TIFF background maps for MOOS-IvP",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sources_parser = subparsers.add_parser("sources", help="List available map sources")
    _add_machine_output(sources_parser)

    plan_parser = subparsers.add_parser(
        "plan", help="Plan an export without downloading"
    )
    _add_map_arguments(plan_parser)
    _add_machine_output(plan_parser)

    build_command = subparsers.add_parser("build", help="Download and build a MOOS map")
    _add_map_arguments(build_command)
    build_command.add_argument(
        "--name", required=True, help="Output basename without suffix"
    )
    build_command.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "moos-maps",
        help="Output directory (default: ~/moos-maps)",
    )
    build_command.add_argument(
        "--no-moos",
        dest="emit_moos",
        action="store_false",
        default=True,
        help="Do not write the default .moos mission snippet",
    )
    build_command.add_argument(
        "--emit-moos",
        dest="emit_moos",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    build_command.add_argument(
        "--no-overwrite",
        dest="overwrite",
        action="store_false",
        default=True,
        help="Refuse to replace existing output files with the same map name",
    )
    build_command.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    build_command.add_argument(
        "--refresh-tiles",
        action="store_true",
        help="Redownload source tiles instead of reusing the local cache",
    )
    build_command.add_argument(
        "--force",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    _add_machine_output(build_command)

    verify_parser = subparsers.add_parser("verify", help="Verify a TIFF/.info bundle")
    verify_parser.add_argument("tiff", type=Path)
    _add_machine_output(verify_parser)

    ui_parser = subparsers.add_parser("ui", help="Launch the local browser UI")
    ui_parser.add_argument(
        "--host", default="127.0.0.1", help="Local bind address (default: 127.0.0.1)"
    )
    ui_parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    ui_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser window",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    if args.command == "sources":
        sources = [source.as_dict() for source in list_sources()]
        if args.json:
            _json_print({"sources": sources})
        else:
            print("Sources:")
            for source in sources:
                capability = "export" if source["export_allowed"] else "preview only"
                print(
                    f"{source['id']:<16} {capability:<12} "
                    f"zoom {source['min_zoom']}-{source['max_zoom']}  {source['name']}"
                )
                if source["note"]:
                    print(f"  {source['note']}")
        return 0

    if args.command == "plan":
        plan = plan_map(_request_from_args(args)).as_dict()
        if args.json:
            _json_print(plan)
        else:
            _print_plan_human(plan)
        return 0

    if args.command == "build":
        request = _request_from_args(args)

        def progress(completed: int, total: int, x: int, y: int) -> None:
            print(
                f"Fetched {completed}/{total} tiles (latest x={x}, y={y})",
                file=sys.stderr,
            )

        result = build_map(request, progress=progress)
        payload = result.as_dict()
        if args.json:
            _json_print(payload)
        else:
            _print_plan_human(
                payload["plan"],
                actual_tiff_size_bytes=payload["verification"]["details"][
                    "file_size_bytes"
                ],
            )
            print(f"TIFF: {payload['tiff_path']}")
            print(f"Info: {payload['info_path']}")
            if payload["moos_path"]:
                print(f"MOOS snippet: {payload['moos_path']}")
            print(
                f"Tiles downloaded: {payload['downloaded_tiles']}; "
                f"cache hits: {payload['cache_hits']}"
            )
        return 0

    if args.command == "verify":
        report = verify_bundle(args.tiff)
        payload = report.as_dict()
        if args.json:
            _json_print(payload)
        else:
            print("PASS" if report.ok else "FAIL")
            print(f"TIFF: {report.tiff_path}")
            print(f"Info: {report.info_path}")
            if "pixel_width" in report.details:
                print(
                    "Image: "
                    f"{report.details['pixel_width']} x "
                    f"{report.details['pixel_height']} pixels, "
                    f"{report.details['mode']} {report.details['format']}"
                )
                size_bytes = report.details["file_size_bytes"]
                print(
                    "TIFF file size: "
                    f"{_format_file_size(size_bytes, precise=True)} "
                    f"({size_bytes:,} bytes)"
                )
            for warning in report.warnings:
                print(f"Warning: {warning}")
            for error in report.errors:
                print(f"Error: {error}", file=sys.stderr)
        return 0 if report.ok else 1

    if args.command == "ui":
        from .web import run_ui

        run_ui(host=args.host, port=args.port, open_browser=not args.no_browser)
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        raise SystemExit(run(args))
    except MoosMapError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
