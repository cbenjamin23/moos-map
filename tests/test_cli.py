from __future__ import annotations

from moos_map.cli import _format_file_size, build_parser


def build_args(*extra: str) -> list[str]:
    return [
        "build",
        "--bounds",
        "-71.088",
        "42.358",
        "-71.087",
        "42.359",
        "--origin",
        "42.3585",
        "-71.0875",
        "--name",
        "harbor",
        *extra,
    ]


def test_build_includes_moos_snippet_by_default() -> None:
    args = build_parser().parse_args(build_args())

    assert args.emit_moos is True
    assert args.source == "esri-world-imagery"


def test_build_can_omit_moos_snippet() -> None:
    args = build_parser().parse_args(build_args("--no-moos"))

    assert args.emit_moos is False


def test_file_size_formatter_handles_small_and_completed_tiffs() -> None:
    assert _format_file_size(46_800) == "47 KB"
    assert _format_file_size(55_820, precise=True) == "55.8 KB"
