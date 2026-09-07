"""Tests for ZotMD's stable, read-only local paper source."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
import pyzotero._client as pyzotero_client_module
from pyzotero import HTTPError, ServerIDMismatchError, UserNotAuthorisedError

import zotmd.paper_source as paper_source
from zotmd import AttachmentAvailability, iter_papers


def api_item(
    key: str,
    *,
    item_type: str = "journalArticle",
    parent: str | None = None,
    version: int = 1,
    library_id: int = 123,
    **data: Any,
) -> dict[str, Any]:
    item_data = {
        "key": key,
        "version": version,
        "itemType": item_type,
        "title": "Synthetic paper",
        "citationKey": "example2026",
        "tags": [{"tag": "paper-source"}],
        **data,
    }
    if parent is not None:
        item_data["parentItem"] = parent
    return {
        "key": key,
        "version": version,
        "library": {"type": "user", "id": library_id},
        "links": {},
        "meta": {},
        "data": item_data,
    }


class RecordingLocalClient:
    """Strict local adapter stand-in for complete snapshot tests."""

    def __init__(
        self,
        *,
        versions: list[int] | None = None,
        top_items: tuple[dict[str, Any], ...] = (),
        children: dict[str, tuple[dict[str, Any], ...] | BaseException] | None = None,
        file_urls: dict[str, str] | None = None,
    ) -> None:
        self.versions = iter(versions or [10, 10])
        self.top_items = top_items
        self.child_items = children or {}
        self.file_urls = file_urls or {}
        self.calls: list[tuple[Any, ...]] = []
        self.closed = False

    def library_version(self, expected_server_id: str | None = None):
        self.calls.append(("library_version", expected_server_id))
        return next(self.versions), "synthetic-server"

    def tagged_top_items(self, tag: str, expected_server_id: str):
        self.calls.append(("tagged_top_items", tag, expected_server_id))
        return self.top_items

    def children(self, item_key: str, expected_server_id: str):
        self.calls.append(("children", item_key, expected_server_id))
        result = self.child_items.get(item_key, ())
        if isinstance(result, BaseException):
            raise result
        return result

    def file_url(self, attachment_key: str, expected_server_id: str):
        self.calls.append(("file_url", attachment_key, expected_server_id))
        return self.file_urls[attachment_key]

    def close(self):
        self.calls.append(("close",))
        self.closed = True


@pytest.fixture
def install_client(monkeypatch) -> Callable[[RecordingLocalClient], None]:
    def install(client: RecordingLocalClient) -> None:
        monkeypatch.setattr(paper_source, "_LocalPaperClient", lambda: client)

    return install


@pytest.mark.parametrize(
    "tag", ["", "   ", "-excluded", "line\nbreak", "nul\x00", "control\u0085"]
)
def test_invalid_tag_is_rejected_before_client_construction(monkeypatch, tag):
    monkeypatch.setattr(
        paper_source,
        "_LocalPaperClient",
        lambda: pytest.fail("client should not be constructed"),
    )

    with pytest.raises(ValueError):
        iter_papers(tag=tag)


def test_non_string_tag_is_rejected_before_client_construction(monkeypatch):
    monkeypatch.setattr(
        paper_source,
        "_LocalPaperClient",
        lambda: pytest.fail("client should not be constructed"),
    )

    with pytest.raises(TypeError):
        iter_papers(tag=1)  # type: ignore[arg-type]


def test_snapshot_filters_exact_manual_tag_and_orders_papers(install_client):
    automatic = api_item("AUTM2345", tags=[{"tag": "paper-source", "type": 1}])
    boolean_type = api_item("BMMN2345", tags=[{"tag": "paper-source", "type": False}])
    float_type = api_item("FMMT2345", tags=[{"tag": "paper-source", "type": 0.0}])
    broader = api_item("BRMAD234", tags=[{"tag": "paper-source-extra"}])
    last = api_item("ZZZZZZZZ")
    first = api_item("AAAAAAAA", library_id=123)
    client = RecordingLocalClient(
        top_items=(last, broader, first, automatic, boolean_type, float_type)
    )
    install_client(client)

    papers = list(iter_papers(tag="paper-source"))

    assert [paper.key for paper in papers] == ["AAAAAAAA", "ZZZZZZZZ"]
    assert client.calls == [
        ("library_version", None),
        ("tagged_top_items", "paper-source", "synthetic-server"),
        ("children", "ZZZZZZZZ", "synthetic-server"),
        ("children", "AAAAAAAA", "synthetic-server"),
        ("library_version", "synthetic-server"),
        ("close",),
    ]


def test_snapshot_parses_complete_metadata_and_identifiers(install_client):
    item = api_item(
        "PARENT23",
        title="Synthetic title",
        citationKey="native2026",
        extra=(
            "Citation Key: fallback2026\n"
            "DOI: 10.9999/CONFLICT\n"
            "arXiv: https://arxiv.org/pdf/2401.01234v2.pdf\n"
            "Ignored: prose"
        ),
        DOI=" https://doi.org/10.1234/EXAMPLE ",
        creators=[
            {
                "creatorType": "author",
                "firstName": "Ada",
                "lastName": "Lovelace",
            },
            {"creatorType": "author", "name": "Synthetic Consortium"},
        ],
        date="2026-09",
        publicationTitle="Synthetic Journal",
        conferenceName="Synthetic Conference",
        publisher="Ignored Publisher",
        url="https://example.invalid/paper",
        tags=[{"tag": "paper-source"}, {"tag": "automatic", "type": 1}],
        collections=["COLLECTION-B", "COLLECTION-A"],
        archive="arXiv",
        archiveLocation="2401.01234v2",
    )
    client = RecordingLocalClient(top_items=(item,))
    install_client(client)

    paper = next(iter_papers(tag="paper-source"))

    assert paper.server_id == "synthetic-server"
    assert paper.library_type == "user"
    assert paper.library_id == 123
    assert paper.citation_key == "native2026"
    assert paper.title == "Synthetic title"
    assert [creator.display_name for creator in paper.creators] == [
        "Ada Lovelace",
        "Synthetic Consortium",
    ]
    assert paper.publication_date == "2026-09"
    assert paper.venues == (
        ("publicationTitle", "Synthetic Journal"),
        ("conferenceName", "Synthetic Conference"),
    )
    assert paper.venue == "Synthetic Journal"
    assert paper.url == "https://example.invalid/paper"
    assert [(tag.name, tag.type) for tag in paper.tags] == [
        ("paper-source", 0),
        ("automatic", 1),
    ]
    assert paper.collection_keys == ("COLLECTION-B", "COLLECTION-A")
    assert [
        (value.kind, value.normalized, value.aliases) for value in paper.identifiers
    ] == [
        ("doi", "10.1234/example", ()),
        ("doi", "10.9999/conflict", ()),
        ("arxiv", "2401.01234v2", ("2401.01234",)),
    ]
    assert "conflicting-doi" in {diagnostic.code for diagnostic in paper.diagnostics}


def test_invalid_identifier_values_are_retained_without_normalized_forms(
    install_client,
):
    item = api_item(
        "PARENT23",
        DOI="not a DOI",
        extra="arXiv: not an arXiv ID",
    )
    client = RecordingLocalClient(top_items=(item,))
    install_client(client)

    paper = next(iter_papers(tag="paper-source"))

    assert [
        (value.kind, value.raw, value.normalized) for value in paper.identifiers
    ] == [
        ("doi", "not a DOI", None),
        ("arxiv", "not an arXiv ID", None),
    ]
    assert {diagnostic.code for diagnostic in paper.diagnostics} == {
        "invalid-doi",
        "invalid-arxiv",
    }


def test_missing_metadata_and_unsupported_top_level_are_diagnostic(install_client):
    item = api_item(
        "NTETMP23",
        item_type="note",
        title=" ",
        citationKey=" ",
        extra="",
    )
    client = RecordingLocalClient(top_items=(item,))
    install_client(client)

    paper = next(iter_papers(tag="paper-source"))

    assert paper.title is None
    assert paper.citation_key is None
    assert paper.primary_pdf is None
    assert {diagnostic.code for diagnostic in paper.diagnostics} == {
        "unsupported-top-level-item",
        "missing-title",
        "missing-citation-key",
    }


def test_available_stored_pdf_uses_enclosure_without_reading_bytes(
    tmp_path, install_client, monkeypatch
):
    path = tmp_path / "synthetic paper.pdf"
    content = b"synthetic pdf"
    path.write_bytes(content)
    md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        title="Synthetic PDF",
        filename="synthetic paper.PDF",
        contentType="application/pdf",
        linkMode="imported_file",
        md5=md5,
        mtime=1234,
    )
    child["links"] = {"enclosure": {"href": path.as_uri()}}
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)
    reads = []
    real_read = paper_source._inspect_local_file

    def inspect_without_read(path):
        reads.append(path)
        return real_read(path)

    monkeypatch.setattr(paper_source, "_inspect_local_file", inspect_without_read)

    paper = next(iter_papers(tag="paper-source"))
    attachment = paper.pdf_attachments[0]

    assert reads == [path]
    assert attachment.availability is AttachmentAvailability.AVAILABLE
    assert attachment.path == path
    assert attachment.local_size == len(content)
    assert paper.primary_pdf is attachment
    assert all(call[0] != "file_url" for call in client.calls)


def test_discovery_and_record_operations_do_not_read_pdf_content(
    tmp_path, install_client, monkeypatch
):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode="imported_file",
    )
    child["links"] = {"enclosure": {"href": path.as_uri()}}
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)
    monkeypatch.setattr(
        os,
        "read",
        lambda *_args: pytest.fail("discovery must not read PDF content"),
    )

    paper = next(iter_papers(tag="paper-source"))
    same_paper = paper

    assert paper == same_paper
    assert paper.primary_pdf is paper.pdf_attachments[0]
    assert "PdfAttachment" in repr(paper.primary_pdf)


def test_stored_pdf_falls_back_to_file_url(tmp_path, install_client):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode="imported_url",
    )
    client = RecordingLocalClient(
        top_items=(parent,),
        children={"PARENT23": (child,)},
        file_urls={"ATTACH23": path.as_uri()},
    )
    install_client(client)

    attachment = next(iter_papers(tag="paper-source")).pdf_attachments[0]

    assert attachment.path == path
    assert ("file_url", "ATTACH23", "synthetic-server") in client.calls


@pytest.mark.parametrize(
    ("link_mode", "expected"),
    [
        ("linked_file", AttachmentAvailability.LINKED),
        ("linked_url", AttachmentAvailability.LINKED),
        ("embedded_image", AttachmentAvailability.UNSUPPORTED),
    ],
)
def test_linked_and_unknown_modes_never_resolve_paths(
    install_client, link_mode, expected
):
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode=link_mode,
    )
    child["links"] = {"enclosure": {"href": "file:///private/paper.pdf"}}
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)

    attachment = next(iter_papers(tag="paper-source")).pdf_attachments[0]

    assert attachment.availability is expected
    assert attachment.path is None
    assert all(call[0] != "file_url" for call in client.calls)


def test_any_second_pdf_candidate_blocks_primary_selection(tmp_path, install_client):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    parent = api_item("PARENT23")
    available = api_item(
        "AVAIL234",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode="imported_file",
    )
    available["links"] = {"enclosure": {"href": path.as_uri()}}
    linked = api_item(
        "LINKED23",
        item_type="attachment",
        parent="PARENT23",
        filename="other.pdf",
        contentType="application/pdf",
        linkMode="linked_file",
    )
    client = RecordingLocalClient(
        top_items=(parent,), children={"PARENT23": (linked, available)}
    )
    install_client(client)

    paper = next(iter_papers(tag="paper-source"))

    assert [attachment.key for attachment in paper.pdf_attachments] == [
        "AVAIL234",
        "LINKED23",
    ]
    assert paper.primary_pdf is None
    assert "multiple-pdf-candidates" in {
        diagnostic.code for diagnostic in paper.diagnostics
    }


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.invalid/paper.pdf",
        "file://example.invalid/private/paper.pdf",
        "file://user@localhost/private/paper.pdf",
        "file:///private/paper.pdf?query=yes",
        "file:///private/paper.pdf#fragment",
        "file:///private/%00paper.pdf",
        "file:///private/%ZZpaper.pdf",
        "file:///private/../paper.pdf",
        "file:relative.pdf",
    ],
)
def test_unsafe_enclosure_uris_are_diagnostic(uri, install_client):
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode="imported_file",
    )
    child["links"] = {"enclosure": {"href": uri}}
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)

    attachment = next(iter_papers(tag="paper-source")).pdf_attachments[0]

    assert attachment.availability is AttachmentAvailability.INVALID
    assert [diagnostic.code for diagnostic in attachment.diagnostics] == [
        "invalid-enclosure-uri"
    ]


def test_percent_encoded_unicode_filename_is_decoded(tmp_path, install_client):
    path = tmp_path / "synthetic-ß.pdf"
    path.write_bytes(b"synthetic pdf")
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename=path.name,
        contentType="application/pdf",
        linkMode="imported_file",
    )
    child["links"] = {"enclosure": {"href": path.as_uri()}}
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)

    attachment = next(iter_papers(tag="paper-source")).pdf_attachments[0]

    assert attachment.path == path
    assert attachment.availability is AttachmentAvailability.AVAILABLE


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("paper.pdf", "text/plain"), ("paper.txt", "application/pdf")],
)
def test_mime_extension_disagreement_is_diagnostic(
    filename, content_type, install_client
):
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename=filename,
        contentType=content_type,
        linkMode="imported_file",
    )
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)

    attachment = next(iter_papers(tag="paper-source")).pdf_attachments[0]

    assert attachment.availability is AttachmentAvailability.INVALID
    assert "mime-extension-mismatch" in {
        diagnostic.code for diagnostic in attachment.diagnostics
    }
    assert all(call[0] != "file_url" for call in client.calls)


@pytest.mark.parametrize("md5", ["", "not-an-md5", 123])
def test_malformed_zotero_md5_is_blocking(md5, tmp_path, install_client):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"synthetic pdf")
    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode="imported_file",
        md5=md5,
    )
    child["links"] = {"enclosure": {"href": path.as_uri()}}
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)

    attachment = next(iter_papers(tag="paper-source")).pdf_attachments[0]

    assert attachment.availability is AttachmentAvailability.INVALID
    assert attachment.path is None
    assert "invalid-zotero-md5" in {
        diagnostic.code for diagnostic in attachment.diagnostics
    }


@pytest.mark.parametrize(
    "kind", ["missing", "empty", "directory", "file-symlink", "parent-symlink"]
)
def test_invalid_local_files_are_diagnostic(tmp_path, install_client, kind):
    if kind == "missing":
        path = tmp_path / "missing" / "paper.pdf"
        expected = (AttachmentAvailability.UNAVAILABLE, "local-file-unavailable")
    elif kind == "empty":
        path = tmp_path / "paper.pdf"
        path.touch()
        expected = (AttachmentAvailability.INVALID, "empty-local-file")
    elif kind == "directory":
        path = tmp_path / "paper.pdf"
        path.mkdir()
        expected = (AttachmentAvailability.INVALID, "not-regular-file")
    elif kind == "file-symlink":
        target = tmp_path / "target.pdf"
        target.write_bytes(b"synthetic pdf")
        path = tmp_path / "paper.pdf"
        path.symlink_to(target)
        expected = (AttachmentAvailability.INVALID, "symlink-local-path")
    else:
        target_directory = tmp_path / "target"
        target_directory.mkdir()
        (target_directory / "paper.pdf").write_bytes(b"synthetic pdf")
        directory = tmp_path / "linked"
        directory.symlink_to(target_directory, target_is_directory=True)
        path = directory / "paper.pdf"
        expected = (AttachmentAvailability.INVALID, "symlink-local-path")

    parent = api_item("PARENT23")
    child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode="imported_file",
    )
    child["links"] = {"enclosure": {"href": path.as_uri()}}
    client = RecordingLocalClient(top_items=(parent,), children={"PARENT23": (child,)})
    install_client(client)

    attachment = next(iter_papers(tag="paper-source")).pdf_attachments[0]

    assert (attachment.availability, attachment.diagnostics[0].code) == expected


def test_unstable_snapshot_retries_three_times_then_fails(install_client):
    versions = [1, 2, 3, 4, 5, 6, 7, 8]
    client = RecordingLocalClient(versions=versions)
    install_client(client)

    with pytest.raises(RuntimeError, match="four snapshot attempts"):
        iter_papers(tag="paper-source")

    assert [call[0] for call in client.calls].count("tagged_top_items") == 4
    assert client.closed


def test_unstable_snapshot_is_discarded_before_a_successful_retry(install_client):
    client = RecordingLocalClient(versions=[1, 2, 3, 3])
    install_client(client)

    assert list(iter_papers(tag="paper-source")) == []
    assert [call[0] for call in client.calls].count("tagged_top_items") == 2
    assert client.closed


def test_later_child_failure_returns_no_partial_iterator(install_client):
    first = api_item("FIRST234")
    second = api_item("SECMND23")
    client = RecordingLocalClient(
        top_items=(first, second),
        children={"SECMND23": ConnectionError("later child failed")},
    )
    install_client(client)

    with pytest.raises(ConnectionError, match="later child failed"):
        iter_papers(tag="paper-source")

    assert client.closed


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.pop("key"),
        lambda item: item.__setitem__("key", "BAD/KEY"),
        lambda item: item.__setitem__("key", "00000000"),
        lambda item: item.__setitem__("key", "OOOOOOOO"),
        lambda item: item.__setitem__("key", "abcd2345"),
        lambda item: item.__setitem__("version", -1),
        lambda item: item["data"].__setitem__("key", "DIFFERENT"),
        lambda item: item["data"].pop("version"),
        lambda item: item["data"].__setitem__("version", None),
        lambda item: item["data"].__setitem__("version", 2),
        lambda item: item["data"].__setitem__("version", True),
        lambda item: item["data"].__setitem__("version", 1.0),
        lambda item: item["data"].pop("itemType"),
        lambda item: item["data"].__setitem__("itemType", ""),
        lambda item: item.__setitem__("library", {"type": "group", "id": 123}),
    ],
)
def test_malformed_top_level_item_invalidates_snapshot(install_client, mutate):
    item = api_item("PARENT23")
    mutate(item)
    client = RecordingLocalClient(top_items=(item,))
    install_client(client)

    with pytest.raises(ValueError):
        iter_papers(tag="paper-source")

    assert client.closed


def test_duplicate_and_wrong_parent_children_invalidate_snapshot(install_client):
    parent = api_item("PARENT23")
    wrong_child = api_item("PARENT23", item_type="note", parent="MTHER234")
    client = RecordingLocalClient(
        top_items=(parent,), children={"PARENT23": (wrong_child,)}
    )
    install_client(client)

    with pytest.raises(ValueError):
        iter_papers(tag="paper-source")


def test_child_without_item_type_invalidates_snapshot(install_client):
    parent = api_item("PARENT23")
    malformed_child = api_item(
        "ATTACH23",
        item_type="attachment",
        parent="PARENT23",
        filename="paper.pdf",
        contentType="application/pdf",
        linkMode="imported_file",
    )
    malformed_child["data"].pop("itemType")
    client = RecordingLocalClient(
        top_items=(parent,), children={"PARENT23": (malformed_child,)}
    )
    install_client(client)

    with pytest.raises(ValueError, match="item type"):
        iter_papers(tag="paper-source")


def test_local_adapter_uses_only_characterized_get_requests(monkeypatch):
    requests: list[httpx2.Request] = []
    clients: list[httpx2.Client] = []
    client_options: list[dict[str, Any]] = []
    real_client = httpx2.Client
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "")

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        headers = {
            "Zotero-Server-ID": "synthetic-server",
            "Last-Modified-Version": "42",
        }
        path = request.url.path
        if path == "/api/users/0/items":
            return httpx2.Response(200, headers=headers, json=[])
        if path == "/api/users/0/items/top":
            return httpx2.Response(200, headers=headers, json=[])
        if path == "/api/users/0/items/PARENT23/children":
            return httpx2.Response(200, headers=headers, json=[])
        if path == "/api/users/0/items/ATTACH23/file/view/url":
            return httpx2.Response(
                200,
                headers={**headers, "Content-Type": "text/plain"},
                text="file:///synthetic/paper.pdf",
            )
        return httpx2.Response(404, headers=headers)

    def client_factory(**kwargs):
        client_options.append(kwargs.copy())
        client = real_client(transport=httpx2.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()

    assert client._zot.local is True
    assert client._zot.library_id == "0"
    assert client._zot.library_type == "users"
    assert client._zot.api_key is None
    assert client._zot.local_api_key is None
    assert client.library_version() == (42, "synthetic-server")
    assert client.tagged_top_items("paper-source", "synthetic-server") == ()
    assert client.children("PARENT23", "synthetic-server") == ()
    assert (
        client.file_url("ATTACH23", "synthetic-server") == "file:///synthetic/paper.pdf"
    )
    client.close()

    assert clients[0].follow_redirects is False
    assert clients[0].is_closed
    assert client_options[0]["trust_env"] is False
    assert [request.method for request in requests] == ["GET"] * 4
    assert all(request.url.host == "localhost" for request in requests)
    assert all(request.headers["zotero-api-version"] == "3" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
    assert "zotero-server-id" not in requests[0].headers
    assert all(
        request.headers.get("zotero-server-id") == "synthetic-server"
        for request in requests[1:]
    )
    top_request = requests[1]
    assert top_request.url.params["tag"] == "paper-source"
    assert top_request.url.params["limit"] == "100"
    assert top_request.url.params["includeTrashed"] == "0"


def test_local_adapter_materializes_valid_pagination_on_the_same_endpoint(monkeypatch):
    requests: list[httpx2.Request] = []
    real_client = httpx2.Client

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        headers = {"Zotero-Server-ID": "synthetic-server"}
        if request.url.params.get("start") is None:
            next_url = (
                "http://localhost:23119/api/users/0/items/top"
                "?tag=paper-source&limit=100&includeTrashed=0"
                "&format=json&locale=en-US&start=100"
            )
            headers["Link"] = f'<{next_url}>; rel="next"'
            return httpx2.Response(200, headers=headers, json=[{"page": 1}])
        return httpx2.Response(200, headers=headers, json=[{"page": 2}])

    def client_factory(**kwargs):
        return real_client(
            transport=httpx2.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()
    try:
        assert client.tagged_top_items("paper-source", "synthetic-server") == (
            {"page": 1},
            {"page": 2},
        )
    finally:
        client.close()

    assert [request.url.path for request in requests] == [
        "/api/users/0/items/top",
        "/api/users/0/items/top",
    ]
    assert requests[1].url.params["start"] == "100"


@pytest.mark.parametrize("next_starts", [(100, 100), (100, 50)])
def test_local_adapter_rejects_pagination_that_does_not_advance(
    monkeypatch, next_starts
):
    requests: list[httpx2.Request] = []
    real_client = httpx2.Client

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        next_start = next_starts[len(requests) - 1]
        next_url = (
            "http://localhost:23119/api/users/0/items/top"
            "?tag=paper-source&limit=100&includeTrashed=0"
            f"&format=json&locale=en-US&start={next_start}"
        )
        return httpx2.Response(
            200,
            headers={
                "Zotero-Server-ID": "synthetic-server",
                "Link": f'<{next_url}>; rel="next"',
            },
            json=[],
        )

    def client_factory(**kwargs):
        return real_client(
            transport=httpx2.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()
    try:
        with pytest.raises(ValueError, match="did not advance"):
            client.tagged_top_items("paper-source", "synthetic-server")
    finally:
        client.close()

    assert len(requests) == 2


def test_local_adapter_rejects_pagination_to_another_endpoint(monkeypatch):
    requests: list[httpx2.Request] = []
    real_client = httpx2.Client

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        next_url = (
            "http://localhost:23119/api/users/0/items/ATTACH23/file"
            "?tag=paper-source&limit=100&includeTrashed=0&start=100"
        )
        return httpx2.Response(
            200,
            headers={
                "Zotero-Server-ID": "synthetic-server",
                "Link": f'<{next_url}>; rel="next"',
            },
            json=[],
        )

    def client_factory(**kwargs):
        return real_client(
            transport=httpx2.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()
    try:
        with pytest.raises(ValueError, match="unsafe pagination target"):
            client.tagged_top_items("paper-source", "synthetic-server")
    finally:
        client.close()

    assert len(requests) == 1


def test_local_adapter_does_not_follow_file_url_redirect(monkeypatch):
    requests: list[httpx2.Request] = []
    real_client = httpx2.Client

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            302,
            headers={
                "Zotero-Server-ID": "synthetic-server",
                "Location": "file:///synthetic/paper.pdf",
            },
        )

    def client_factory(**kwargs):
        return real_client(
            transport=httpx2.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()
    try:
        with pytest.raises(HTTPError):
            client.file_url("ATTACH23", "synthetic-server")
    finally:
        client.close()

    assert len(requests) == 1
    assert requests[0].url.path.endswith("/ATTACH23/file/view/url")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Zotero-Server-ID": "server"},
        {"Last-Modified-Version": "42"},
        {"Zotero-Server-ID": "server", "Last-Modified-Version": "invalid"},
    ],
)
def test_local_adapter_requires_raw_version_and_server_headers(monkeypatch, headers):
    real_client = httpx2.Client

    def client_factory(**kwargs):
        return real_client(
            transport=httpx2.MockTransport(
                lambda _request: httpx2.Response(200, headers=headers, json=[])
            ),
            **kwargs,
        )

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()
    try:
        with pytest.raises(ValueError):
            client.library_version()
    finally:
        client.close()


def test_local_adapter_rejects_a_changed_response_server_id(monkeypatch):
    real_client = httpx2.Client
    responses = iter(("first-server", "second-server"))

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={
                "Zotero-Server-ID": next(responses),
                "Last-Modified-Version": "42",
            },
            json=[],
        )

    def client_factory(**kwargs):
        return real_client(
            transport=httpx2.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()
    try:
        assert client.library_version() == (42, "first-server")
        with pytest.raises(ValueError, match="identity changed"):
            client.library_version("first-server")
    finally:
        client.close()


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (403, "Local API disabled", UserNotAuthorisedError),
        (412, "Zotero-Server-ID does not match", ServerIDMismatchError),
    ],
)
def test_local_adapter_propagates_pyzotero_errors(monkeypatch, status, body, error):
    real_client = httpx2.Client

    def client_factory(**kwargs):
        return real_client(
            transport=httpx2.MockTransport(
                lambda _request: httpx2.Response(
                    status,
                    headers={"Zotero-Server-ID": "synthetic-server"},
                    text=body,
                )
            ),
            **kwargs,
        )

    monkeypatch.setattr(pyzotero_client_module.httpx2, "Client", client_factory)
    client = paper_source._LocalPaperClient()
    try:
        with pytest.raises(error):
            client.library_version()
    finally:
        client.close()
