"""Characterization tests for template change detection."""

import pytest

from zotmd.core.state_manager import TemplateVersion
from zotmd.core.template_manager import TemplateChangeDetector


def test_compute_template_hash_uses_sha256():
    content = "template: {{ title }}\n"

    assert TemplateChangeDetector.compute_template_hash(content) == (
        "fddc347fc118bf924236f08b78a1ec0dc8dee66a457b9a34a78ff196cee3a60d"
    )


def test_builtin_template_identifier():
    assert TemplateChangeDetector.get_template_identifier(None) == "built-in"


def test_custom_template_identifier_is_absolute_and_resolved(tmp_path):
    template_path = tmp_path / "templates" / ".." / "custom.md.j2"

    assert TemplateChangeDetector.get_template_identifier(template_path) == str(
        (tmp_path / "custom.md.j2").resolve()
    )


@pytest.mark.parametrize(
    ("stored_version", "expected"),
    [
        pytest.param(None, False, id="no-stored-version"),
        pytest.param(
            TemplateVersion("current-hash", "built-in"),
            False,
            id="matching-version",
        ),
        pytest.param(
            TemplateVersion("old-hash", "built-in"),
            True,
            id="content-changed",
        ),
        pytest.param(
            TemplateVersion("current-hash", "/templates/old.md.j2"),
            True,
            id="identifier-changed",
        ),
        pytest.param(
            TemplateVersion(
                "current-hash",
                "built-in",
                render_contract_version=1,
            ),
            True,
            id="render-contract-changed",
        ),
    ],
)
def test_has_template_changed(stored_version, expected):
    assert (
        TemplateChangeDetector.has_template_changed(
            "current-hash", "built-in", stored_version
        )
        is expected
    )
