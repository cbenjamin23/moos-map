from __future__ import annotations

import pytest

from moos_map.cli import _format_file_size, _request_from_args, build_parser
from moos_map.errors import ValidationError


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


@pytest.mark.parametrize("command", ["plan", "build"])
@pytest.mark.parametrize("longitudes", [("179.999", "-179.999"), ("-179.999", "179.999")])
def test_ambiguous_date_line_corners_require_explicit_wide_bounds(
    command: str, longitudes: tuple[str, str]
) -> None:
    parser = build_parser()
    args = [command, "--corners", "0", longitudes[0], "0.001", longitudes[1]]
    if command == "build":
        args += ["--name", "dateline"]

    with pytest.raises(ValidationError, match="Split a date-line crossing into two exports"):
        _request_from_args(parser.parse_args(args))

    wide = _request_from_args(parser.parse_args([*args, "--allow-wide-bounds"]))
    assert (wide.bounds.west, wide.bounds.east) == (-179.999, 179.999)


@pytest.mark.parametrize("longitudes", [("179.999", "180"), ("-179.999", "-180")])
def test_cli_accepts_bounds_that_touch_the_date_line(longitudes: tuple[str, str]) -> None:
    args = build_parser().parse_args(["plan", "--corners", "0", longitudes[0], "0.001", longitudes[1]])
    bounds = _request_from_args(args).bounds

    assert bounds.east - bounds.west == pytest.approx(0.001)


def test_explicit_origin_overrides_map_center() -> None:
    args = build_parser().parse_args(
        build_args("--origin", "42.3584", "-71.0874")
    )

    assert _request_from_args(args).origin.latitude == 42.3584
    assert _request_from_args(args).origin.longitude == -71.0874


def test_texture_target_can_be_set_in_the_cli() -> None:
    args = build_parser().parse_args(build_args("--max-texture-dimension", "8192"))
    assert _request_from_args(args).max_texture_dimension == 8192


def test_build_can_omit_moos_snippet() -> None:
    args = build_parser().parse_args(build_args("--no-moos"))

    assert args.emit_moos is False


def test_file_size_formatter_handles_small_and_completed_tiffs() -> None:
    assert _format_file_size(46_800) == "47 KB"
    assert _format_file_size(55_820, precise=True) == "55.8 KB"
