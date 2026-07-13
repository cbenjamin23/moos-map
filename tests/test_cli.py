from __future__ import annotations

from moos_map.cli import _format_file_size, _request_from_args, build_parser


def build_args(*extra: str) -> list[str]:
    return [
        "build",
        "--corners",
        "42.358",
        "-71.088",
        "42.359",
        "-71.087",
        "--name",
        "harbor",
        *extra,
    ]


def test_build_includes_moos_snippet_by_default() -> None:
    args = build_parser().parse_args(build_args())
    request = _request_from_args(args)

    assert args.emit_moos is True
    assert args.source == "esri-world-imagery"
    assert request.origin.latitude == 42.3585
    assert request.origin.longitude == -71.0875


def test_corners_accept_either_diagonal_order() -> None:
    first = _request_from_args(build_parser().parse_args(build_args()))
    reversed_corners = _request_from_args(
        build_parser().parse_args(
            [
                "build",
                "--corners",
                "42.359",
                "-71.087",
                "42.358",
                "-71.088",
                "--name",
                "harbor",
            ]
        )
    )

    assert reversed_corners.bounds == first.bounds
    assert reversed_corners.origin == first.origin


def test_explicit_origin_overrides_map_center() -> None:
    args = build_parser().parse_args(
        build_args("--origin", "42.3584", "-71.0874")
    )

    assert _request_from_args(args).origin.latitude == 42.3584
    assert _request_from_args(args).origin.longitude == -71.0874


def test_build_can_omit_moos_snippet() -> None:
    args = build_parser().parse_args(build_args("--no-moos"))

    assert args.emit_moos is False


def test_file_size_formatter_handles_small_and_completed_tiffs() -> None:
    assert _format_file_size(46_800) == "47 KB"
    assert _format_file_size(55_820, precise=True) == "55.8 KB"
