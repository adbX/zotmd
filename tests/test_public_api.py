"""Tests for package-root exports and import isolation."""

from __future__ import annotations

import subprocess
import sys

import zotmd


def test_package_root_exports_exact_public_api():
    assert zotmd.__all__ == [
        "__version__",
        "AttachmentAvailability",
        "Creator",
        "Diagnostic",
        "FileFingerprint",
        "Identifier",
        "Paper",
        "PdfAttachment",
        "Tag",
        "iter_papers",
    ]
    assert all(hasattr(zotmd, name) for name in zotmd.__all__)


def test_isolated_package_import_does_not_load_runtime_integrations(tmp_path):
    script = """
import socket
import sys

def forbidden(*args, **kwargs):
    raise AssertionError("package import attempted network access")

socket.create_connection = forbidden
import zotmd

assert zotmd.__version__
forbidden_modules = (
    "pyzotero",
    "sqlite3",
    "zotmd.cli",
    "zotmd.config",
    "zotmd.core",
    "zotmd.file_ops",
)
loaded = tuple(sys.modules)
assert not any(
    name == prefix or name.startswith(prefix + ".")
    for name in loaded
    for prefix in forbidden_modules
), sorted(name for name in loaded if name.startswith(("pyzotero", "zotmd")))
"""

    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
