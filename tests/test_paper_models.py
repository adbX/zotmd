"""Tests for immutable local paper-source records and file fingerprinting."""

from __future__ import annotations

import hashlib
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from zotmd import (
    AttachmentAvailability,
    Creator,
    Diagnostic,
    Identifier,
    Paper,
    PdfAttachment,
    Tag,
)
from zotmd.models.paper import _inspect_local_file


def available_attachment(path: Path, *, zotero_md5: str | None = None) -> PdfAttachment:
    file_stat, problem = _inspect_local_file(path)
    assert problem is None
    assert file_stat is not None
    return PdfAttachment(
        key="ATTACHMENT",
        version=12,
        parent_key="PARENT",
        title="Synthetic PDF",
        filename="synthetic.pdf",
        content_type="application/pdf",
        link_mode="imported_file",
        enclosure_uri=path.as_uri(),
        zotero_md5=zotero_md5,
        zotero_mtime=1234,
        path=path,
        local_size=file_stat.st_size,
        local_mtime_ns=file_stat.st_mtime_ns,
        local_device=file_stat.st_dev,
        local_inode=file_stat.st_ino,
        availability=AttachmentAvailability.AVAILABLE,
    )


def test_supporting_records_are_frozen_and_copy_nested_collections():
    aliases = ["2401.01234"]
    identifier = Identifier("arxiv", "2401.01234v2", "2401.01234v2", aliases)
    paper = Paper(
        server_id="server",
        library_type="user",
        library_id=123,
        key="PARENT",
        version=1,
        item_type="journalArticle",
        citation_key="example2026",
        title="Synthetic paper",
        creators=[Creator("author", "Ada", "Lovelace")],
        venues=[["publicationTitle", "Synthetic Journal"]],
        tags=[Tag("example")],
        collection_keys=["COLLECTION"],
        identifiers=[identifier],
        diagnostics=[Diagnostic("notice", "Synthetic diagnostic", False)],
    )
    aliases.append("changed")

    assert identifier.aliases == ("2401.01234",)
    assert paper.creators == (Creator("author", "Ada", "Lovelace"),)
    assert paper.venues == (("publicationTitle", "Synthetic Journal"),)
    assert paper.zotero_uri == "zotero://select/library/items/PARENT"
    with pytest.raises(FrozenInstanceError):
        paper.title = "changed"  # type: ignore[misc]


def test_creator_display_name_preserves_single_and_two_field_names():
    assert Creator("author", "Ada", "Lovelace").display_name == "Ada Lovelace"
    assert Creator("author", name="World Health Organization").display_name == (
        "World Health Organization"
    )


def test_primary_pdf_requires_one_available_unblocked_candidate(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    attachment = available_attachment(path)
    paper = Paper(
        "server",
        "user",
        123,
        "PARENT",
        1,
        "journalArticle",
        "example2026",
        "Synthetic paper",
        pdf_attachments=(attachment,),
    )

    assert paper.primary_pdf is attachment
    assert (
        Paper(
            "server",
            "user",
            123,
            "PARENT",
            1,
            "journalArticle",
            "example2026",
            "Synthetic paper",
            pdf_attachments=(attachment, attachment),
        ).primary_pdf
        is None
    )
    assert (
        Paper(
            "server",
            "user",
            123,
            "PARENT",
            1,
            "journalArticle",
            "example2026",
            "Synthetic paper",
            pdf_attachments=(attachment,),
            diagnostics=(Diagnostic("blocked", "Synthetic block", True),),
        ).primary_pdf
        is None
    )


def test_attachment_repr_hides_enclosure_uri_and_path(tmp_path):
    path = tmp_path / "private-paper.pdf"
    path.write_bytes(b"synthetic pdf")
    attachment = available_attachment(path)

    representation = repr(attachment)

    assert str(path) not in representation
    assert path.as_uri() not in representation


def test_fingerprint_streams_sha256_and_md5_without_caching(tmp_path):
    content = b"synthetic pdf bytes" * 1024
    path = tmp_path / "paper.pdf"
    path.write_bytes(content)
    expected_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
    attachment = available_attachment(path, zotero_md5=expected_md5.upper())

    first = attachment.fingerprint()
    second = attachment.fingerprint()

    assert first == second
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert first.md5 == expected_md5
    assert first.size == len(content)
    assert first.device == path.stat().st_dev
    assert first.inode == path.stat().st_ino


def test_fingerprint_rejects_zotero_md5_mismatch(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    attachment = available_attachment(path, zotero_md5="0" * 32)

    with pytest.raises(ValueError, match="does not match Zotero's MD5"):
        attachment.fingerprint()


@pytest.mark.parametrize("change", ["size", "mtime", "inode"])
def test_fingerprint_rejects_file_changed_after_discovery(tmp_path, change):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"original synthetic pdf")
    attachment = available_attachment(path)

    if change == "size":
        path.write_bytes(b"different length synthetic pdf")
    elif change == "mtime":
        original = path.stat()
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
    else:
        replacement = tmp_path / "replacement.pdf"
        replacement.write_bytes(b"original synthetic pdf")
        replacement.replace(path)

    with pytest.raises(OSError, match="could not be read stably"):
        attachment.fingerprint()


def test_fingerprint_rejects_parent_replaced_by_symlink(tmp_path):
    directory = tmp_path / "stored"
    directory.mkdir()
    path = directory / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    attachment = available_attachment(path)
    moved = tmp_path / "moved"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)

    with pytest.raises(OSError, match="safe local path"):
        attachment.fingerprint()


def test_fingerprint_propagates_a_privacy_safe_io_error(tmp_path, monkeypatch):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    attachment = available_attachment(path)

    monkeypatch.setattr(os, "read", lambda *_args: (_ for _ in ()).throw(OSError()))

    with pytest.raises(OSError, match="could not be read stably") as raised:
        attachment.fingerprint()
    assert str(path) not in str(raised.value)


def test_unavailable_attachment_cannot_be_fingerprinted():
    attachment = PdfAttachment(
        key="ATTACHMENT",
        version=1,
        parent_key="PARENT",
        title=None,
        filename="paper.pdf",
        content_type="application/pdf",
        link_mode="imported_file",
    )

    with pytest.raises(OSError, match="not an available local file"):
        attachment.fingerprint()
