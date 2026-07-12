from __future__ import annotations

import pytest

from moos_map.errors import ValidationError
from moos_map.sources import resolve_source


def test_custom_xyz_requires_all_placeholders() -> None:
    with pytest.raises(ValidationError, match="must contain"):
        resolve_source("custom", custom_url_template="https://example/{z}/{x}.png")


def test_custom_xyz_export_requires_explicit_terms_acknowledgement() -> None:
    template = "https://example/{z}/{x}/{y}.png"

    preview = resolve_source("custom", custom_url_template=template)
    export = resolve_source(
        "custom",
        custom_url_template=template,
        accept_custom_source_terms=True,
    )

    assert preview.preview_allowed is True
    assert preview.export_allowed is False
    assert export.export_allowed is True
