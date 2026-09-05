#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Validate ZotMD source and wheel release artifacts."""

import argparse
import hashlib
import re
import stat
import tarfile
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

_FORBIDDEN_PARTS = {
    ".cache",
    ".claude",
    ".cursor",
    ".git",
    ".github",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".rumdl_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "dev",
    "htmlcov",
    "plans",
    "prompts",
    "raw",
    "reference",
    "references",
    "site",
    "wheels",
}
_FORBIDDEN_FILENAMES = {
    ".coverage",
    ".ds_store",
    "coverage.xml",
    "thumbs.db",
    "zotero_sync.log",
}
_DATABASE_SUFFIXES = (".db", ".db3", ".sqlite", ".sqlite3")
_DATABASE_SIDECARS = ("-journal", "-shm", "-wal")
_HOME_PATHS = (
    re.compile(
        rb"(?<![A-Za-z0-9:])/Users/[A-Za-z0-9._-]+"
        rb"(?=[/\\]|[^A-Za-z0-9._-]|$)"
    ),
    re.compile(
        rb"(?<![A-Za-z0-9:])/home/[A-Za-z0-9._-]+"
        rb"(?=[/\\]|[^A-Za-z0-9._-]|$)"
    ),
    re.compile(rb"(?i)(?:[A-Z]:[\\/]|\\\\)Users[\\/][^\\/\s\"']+(?=[\\/\s\"']|$)"),
)


class ArtifactError(ValueError):
    """Raised when a distribution violates a release contract."""


def _member_parts(name: str) -> tuple[str, ...]:
    if not name or "\\" in name:
        raise ArtifactError(f"unsafe archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ArtifactError(f"unsafe archive path: {name!r}")
    return path.parts


def _is_database(name: str) -> bool:
    lower = name.casefold()
    return any(
        lower.endswith(suffix)
        or any(lower.endswith(f"{suffix}{sidecar}") for sidecar in _DATABASE_SIDECARS)
        for suffix in _DATABASE_SUFFIXES
    )


def _inspect_member(name: str, content: bytes) -> None:
    parts = _member_parts(name)
    folded_parts = {part.casefold() for part in parts}
    if folded_parts & _FORBIDDEN_PARTS:
        raise ArtifactError(f"forbidden archive directory: {name}")
    filename = parts[-1].casefold()
    if (
        filename in _FORBIDDEN_FILENAMES
        or filename.endswith((".pyc", ".pyo"))
        or _is_database(filename)
    ):
        raise ArtifactError(f"forbidden generated file: {name}")
    if any(pattern.search(content) for pattern in _HOME_PATHS):
        raise ArtifactError(f"absolute home path in archive content: {name}")


def _require_metadata(content: bytes, name: str, version: str, label: str) -> None:
    metadata = BytesParser(policy=policy.default).parsebytes(content)
    if metadata["Name"] != name:
        raise ArtifactError(f"{label} has the wrong project name")
    if metadata["Version"] != version:
        raise ArtifactError(f"{label} has the wrong project version")
    if metadata["Requires-Python"] != ">=3.13":
        raise ArtifactError(f"{label} has the wrong Python requirement")
    if metadata["Description-Content-Type"] != "text/markdown":
        raise ArtifactError(f"{label} does not declare a Markdown description")
    if not metadata.get_payload().lstrip().startswith("# ZotMD"):
        raise ArtifactError(f"{label} does not contain the project README")


def _validate_sdist(path: Path, name: str, version: str) -> None:
    root = f"{name}-{version}"
    contents: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as archive:
        seen: set[str] = set()
        for member in archive.getmembers():
            if member.name in seen:
                raise ArtifactError(f"duplicate source archive member: {member.name}")
            seen.add(member.name)
            parts = _member_parts(member.name)
            if parts[0] != root:
                raise ArtifactError(
                    f"source archive member outside {root}: {member.name}"
                )
            if member.issym() or member.islnk() or member.isdev():
                raise ArtifactError(f"unsafe source archive member type: {member.name}")
            if not member.isfile() and not member.isdir():
                raise ArtifactError(f"unsupported source archive member: {member.name}")
            content = b""
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ArtifactError(
                        f"unreadable source archive member: {member.name}"
                    )
                content = extracted.read()
                contents[member.name] = content
            _inspect_member(member.name, content)

    required = {
        f"{root}/CHANGELOG.md",
        f"{root}/LICENSE",
        f"{root}/PKG-INFO",
        f"{root}/README.md",
        f"{root}/ROADMAP.md",
        f"{root}/SECURITY.md",
        f"{root}/pyproject.toml",
        f"{root}/src/zotmd/py.typed",
        f"{root}/src/zotmd/templates/default.md.j2",
        f"{root}/tools/check_release_artifacts.py",
        f"{root}/uv.lock",
    }
    missing = required - contents.keys()
    if missing:
        raise ArtifactError(f"source archive is missing: {', '.join(sorted(missing))}")
    _require_metadata(contents[f"{root}/PKG-INFO"], name, version, "source metadata")


def _validate_wheel(path: Path, name: str, version: str) -> None:
    dist_info = f"{name}-{version}.dist-info"
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ArtifactError("wheel contains duplicate members")
        contents: dict[str, bytes] = {}
        for entry in entries:
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArtifactError(f"wheel contains a symbolic link: {entry.filename}")
            content = b"" if entry.is_dir() else archive.read(entry)
            if not entry.is_dir():
                contents[entry.filename] = content
            _inspect_member(entry.filename, content)

    required = {
        "zotmd/__init__.py",
        "zotmd/py.typed",
        "zotmd/templates/default.md.j2",
        f"{dist_info}/METADATA",
        f"{dist_info}/WHEEL",
        f"{dist_info}/entry_points.txt",
        f"{dist_info}/licenses/LICENSE",
    }
    missing = required - contents.keys()
    if missing:
        raise ArtifactError(f"wheel is missing: {', '.join(sorted(missing))}")
    _require_metadata(
        contents[f"{dist_info}/METADATA"], name, version, "wheel metadata"
    )
    wheel_metadata = contents[f"{dist_info}/WHEEL"]
    if (
        b"Root-Is-Purelib: true" not in wheel_metadata
        or b"Tag: py3-none-any" not in wheel_metadata
    ):
        raise ArtifactError("wheel is not a universal pure-Python wheel")
    if b"zotmd = zotmd.cli:main" not in contents[f"{dist_info}/entry_points.txt"]:
        raise ArtifactError("wheel does not contain the zotmd console entry point")


def validate_artifacts(dist_dir: Path, name: str, version: str) -> dict[str, str]:
    """Validate exactly one expected source archive and universal wheel."""
    expected = {
        f"{name}-{version}.tar.gz",
        f"{name}-{version}-py3-none-any.whl",
    }
    files = {path.name: path for path in dist_dir.iterdir() if path.is_file()}
    build_ignore = files.pop(".gitignore", None)
    if (
        build_ignore is not None
        and build_ignore.read_text(encoding="utf-8").strip() != "*"
    ):
        raise ArtifactError("distribution directory contains an unexpected .gitignore")
    if files.keys() != expected:
        raise ArtifactError(
            "distribution directory must contain exactly: "
            + ", ".join(sorted(expected))
        )
    _validate_sdist(files[f"{name}-{version}.tar.gz"], name, version)
    _validate_wheel(files[f"{name}-{version}-py3-none-any.whl"], name, version)
    return {
        filename: hashlib.sha256(path.read_bytes()).hexdigest()
        for filename, path in sorted(files.items())
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--name", default="zotmd")
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    try:
        digests = validate_artifacts(args.dist_dir, args.name, args.version)
    except (ArtifactError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    for filename, digest in digests.items():
        print(f"{digest}  {filename}")


if __name__ == "__main__":
    main()
