"""Tests for strict release archive validation."""

import runpy
from pathlib import Path

import pytest

_VALIDATOR = runpy.run_path(
    Path(__file__).parents[1] / "tools" / "check_release_artifacts.py"
)
ArtifactError = _VALIDATOR["ArtifactError"]
_inspect_member = _VALIDATOR["_inspect_member"]
_member_parts = _VALIDATOR["_member_parts"]
_require_metadata = _VALIDATOR["_require_metadata"]


def distribution_metadata(*requirements: str) -> bytes:
    headers = [
        "Metadata-Version: 2.4",
        "Name: zotmd",
        "Version: 0.5.0",
        "Requires-Python: >=3.13",
        "Description-Content-Type: text/markdown",
        *(f"Requires-Dist: {requirement}" for requirement in requirements),
    ]
    return ("\n".join(headers) + "\n\n# ZotMD\n").encode()


@pytest.mark.parametrize(
    "name",
    ["/absolute/file", "../outside", "root/../../outside", r"root\windows"],
)
def test_archive_paths_reject_traversal_and_platform_ambiguity(name):
    with pytest.raises(ArtifactError, match="unsafe archive path"):
        _member_parts(name)


@pytest.mark.parametrize(
    "name",
    [
        "root/.rumdl_cache/result",
        "root/plans/release.md",
        "root/state.sqlite-wal",
        "root/cache.pyc",
    ],
)
def test_archive_members_reject_private_and_generated_files(name):
    with pytest.raises(ArtifactError):
        _inspect_member(name, b"")


@pytest.mark.parametrize(
    "content",
    [
        b"/Users/" + b"example/project",
        b"/Users/" + b"example",
        b"/home/" + b"example/project",
        b"/home/" + b"example",
        b"C:/Users/" + b"example/project",
        b"C:/Users/" + b"example",
        b"C:\\Users\\" + b"example\\project",
    ],
)
def test_archive_content_rejects_absolute_home_paths(content):
    with pytest.raises(ArtifactError, match="absolute home path"):
        _inspect_member("root/README.md", content)


def test_archive_content_accepts_portable_home_paths():
    _inspect_member("root/README.md", b"~/Documents/references")


def test_archive_content_accepts_public_url_paths():
    _inspect_member("root/README.md", b"https://example.test/home/user/project")


def test_archive_content_rejects_markdown_wrapped_home_path():
    with pytest.raises(ArtifactError, match="absolute home path"):
        _inspect_member("root/README.md", b"`/home/" + b"example`")


def test_distribution_metadata_accepts_exact_runtime_dependency_bounds():
    _require_metadata(
        distribution_metadata("pyzotero<2,>=1.15.1", "httpx2<3,>=2.12.0"),
        "zotmd",
        "0.5.0",
        "wheel metadata",
    )


@pytest.mark.parametrize(
    "requirements",
    [
        ("pyzotero>=1.15.1", "httpx2<3,>=2.12.0"),
        ("pyzotero<2,>=1.15.1", "httpx2>=2.12.0"),
        ("pyzotero<20,>=1.15.1", "httpx2<3,>=2.12.0"),
        ("pyzotero<2,>=1.15.1", "httpx2<30,>=2.12.0"),
    ],
)
def test_distribution_metadata_rejects_inexact_runtime_dependency_bounds(
    requirements,
):
    with pytest.raises(ArtifactError, match="requirement"):
        _require_metadata(
            distribution_metadata(*requirements),
            "zotmd",
            "0.5.0",
            "wheel metadata",
        )
