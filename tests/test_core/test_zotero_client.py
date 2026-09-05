"""Characterization tests for the Pyzotero client wrapper."""

from typing import Any

import httpx2
import pytest
import pyzotero._client as pyzotero_client_module
from pyzotero import (
    HTTPError,
    TooManyRetriesError,
    UserNotAuthorisedError,
)
from pyzotero import Zotero as Pyzotero

import zotmd.core.zotero_client as zotero_client_module
from zotmd.core.zotero_client import ZoteroClient


class RecordingZotero:
    """Small Pyzotero stand-in that rejects any uncharacterized method."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.failures: dict[str, BaseException] = {}
        self.version = 41
        self.top_result = object()
        self.items_result = object()
        self.everything_result: list[dict] = []
        self.everything_results: dict[int, list[dict]] = {}
        self.children_results: dict[str, list[dict] | BaseException] = {}
        self.deleted_result: dict = {
            "items": [],
            "collections": [],
            "searches": [],
            "tags": [],
        }

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if failure := self.failures.get(name):
            raise failure

    def last_modified_version(self) -> int:
        self._record("last_modified_version")
        return self.version

    def top(self, **kwargs: Any) -> object:
        self._record("top", **kwargs)
        return self.top_result

    def items(self, **kwargs: Any) -> object:
        self._record("items", **kwargs)
        return self.items_result

    def everything(self, initial_request: object) -> list[dict]:
        self._record("everything", initial_request)
        if initial_request is self.top_result or initial_request is self.items_result:
            return self.everything_result
        assert isinstance(initial_request, list)
        return self.everything_results.get(id(initial_request), initial_request)

    def children(self, item_key: str) -> list[dict]:
        self._record("children", item_key)
        result = self.children_results.get(item_key, [])
        if isinstance(result, BaseException):
            raise result
        return result

    def deleted(self, **kwargs: Any) -> dict:
        self._record("deleted", **kwargs)
        return self.deleted_result

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Unexpected Pyzotero method access: {name}")


@pytest.fixture
def patched_client(monkeypatch):
    api = RecordingZotero()
    constructor_calls = []

    def constructor(library_id: str, library_type: str, api_key: str):
        constructor_calls.append((library_id, library_type, api_key))
        return api

    monkeypatch.setattr(zotero_client_module, "Zotero", constructor)

    client = ZoteroClient("12345", "secret")
    return client, api, constructor_calls


@pytest.fixture
def transport_client(monkeypatch):
    clients = []

    def create(handler):
        http = httpx2.Client(transport=httpx2.MockTransport(handler))
        api = Pyzotero("12345", "user", "secret", client=http)
        monkeypatch.setattr(zotero_client_module, "Zotero", lambda *args: api)
        clients.append(http)
        return ZoteroClient("12345", "secret")

    yield create

    for client in clients:
        client.close()


def test_constructor_delegates_personal_library_credentials(monkeypatch):
    api = RecordingZotero()
    calls = []

    def constructor(library_id: str, received_type: str, api_key: str):
        calls.append((library_id, received_type, api_key))
        return api

    monkeypatch.setattr(zotero_client_module, "Zotero", constructor)

    client = ZoteroClient("98765", "api-key")

    assert calls == [("98765", "user", "api-key")]
    assert client.library_id == "98765"
    assert client.zot is api


def test_get_library_version_returns_pyzotero_result(patched_client):
    client, api, _ = patched_client
    api.version = 314

    assert client.get_library_version() == 314
    assert api.calls == [("last_modified_version", (), {})]


@pytest.mark.parametrize(
    ("method_name", "args", "source_name", "source_kwargs"),
    [
        (
            "get_all_items",
            (17,),
            "top",
            {"limit": 17, "includeTrashed": 1},
        ),
        (
            "get_items_since_version",
            (72, 18),
            "top",
            {"limit": 18, "since": 72, "includeTrashed": 1},
        ),
        (
            "get_all_annotations",
            (19,),
            "items",
            {"itemType": "annotation", "limit": 19},
        ),
        (
            "get_all_attachments",
            (20,),
            "items",
            {"itemType": "attachment", "limit": 20},
        ),
    ],
)
def test_paginated_reads_delegate_to_everything(
    patched_client, method_name, args, source_name, source_kwargs
):
    client, api, _ = patched_client
    api.everything_result = [{"key": "first"}, {"key": "last"}]
    source_result = api.top_result if source_name == "top" else api.items_result

    result = getattr(client, method_name)(*args)

    assert result is api.everything_result
    assert api.calls == [
        (source_name, (), source_kwargs),
        ("everything", (source_result,), {}),
    ]


def test_get_item_children_paginates_for_item_key(patched_client):
    client, api, _ = patched_client
    first_page = [{"key": "FIRST"}]
    all_children = [*first_page, {"key": "LAST"}]
    api.children_results["PARENT"] = first_page
    api.everything_results[id(first_page)] = all_children

    assert client.get_item_children("PARENT") is all_children
    assert api.calls == [
        ("children", ("PARENT",), {}),
        ("everything", (first_page,), {}),
    ]


def test_get_deleted_items_passes_since_version(patched_client):
    client, api, _ = patched_client
    deleted = {
        "items": ["ITEM"],
        "collections": ["COLLECTION"],
        "searches": [],
        "tags": [],
    }
    api.deleted_result = deleted

    assert client.get_deleted_items(88) is deleted
    assert api.calls == [("deleted", (), {"since": 88})]


@pytest.mark.parametrize(
    ("method_name", "args", "failing_call", "error"),
    [
        (
            "get_library_version",
            (),
            "last_modified_version",
            RuntimeError("version unavailable"),
        ),
        (
            "get_all_items",
            (9,),
            "everything",
            ConnectionError("pagination failed"),
        ),
        (
            "get_deleted_items",
            (10,),
            "deleted",
            ValueError("invalid response"),
        ),
    ],
)
def test_read_errors_are_reraised(
    patched_client, method_name, args, failing_call, error
):
    client, api, _ = patched_client
    api.failures[failing_call] = error

    with pytest.raises(type(error)) as raised:
        getattr(client, method_name)(*args)

    assert raised.value is error


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [(401, UserNotAuthorisedError), (503, HTTPError)],
)
def test_pyzotero_http_errors_surface_through_wrapper(
    transport_client, status_code, expected_error
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(status_code, text="request failed")

    client = transport_client(handler)

    with pytest.raises(expected_error):
        client.get_library_version()

    assert len(requests) == 1
    assert requests[0].method == "GET"


def test_pyzotero_honors_retry_after_then_returns_success(
    transport_client, monkeypatch
):
    requests = []
    sleeps = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx2.Response(429, headers={"Retry-After": "1"})
        return httpx2.Response(200, headers={"Last-Modified-Version": "42"})

    monkeypatch.setattr(pyzotero_client_module.time, "sleep", sleeps.append)
    client = transport_client(handler)

    assert client.get_library_version() == 42
    assert len(requests) == 2
    assert all(request.method == "GET" for request in requests)
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 1


def test_pyzotero_raises_after_rate_limit_retry_exhaustion(
    transport_client, monkeypatch
):
    requests = []
    sleeps = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(429, headers={"Retry-After": "1"})

    monkeypatch.setattr(pyzotero_client_module.time, "sleep", sleeps.append)
    client = transport_client(handler)

    with pytest.raises(TooManyRetriesError, match="after 3 attempts"):
        client.get_library_version()

    assert len(requests) == 3
    assert all(request.method == "GET" for request in requests)
    assert len(sleeps) == 2


def test_get_annotations_recurses_into_supported_attachments(patched_client):
    client, api, _ = patched_client
    pdf_annotation = {"key": "PDF-ANNOT", "data": {"itemType": "annotation"}}
    epub_annotation = {"key": "EPUB-ANNOT", "data": {"itemType": "annotation"}}
    api.children_results["ITEM"] = [
        {"key": "NOTE", "data": {"itemType": "note"}},
        {
            "key": "PDF",
            "data": {
                "itemType": "attachment",
                "contentType": "application/pdf",
                "linkMode": "imported_file",
            },
        },
        {
            "key": "EPUB",
            "data": {
                "itemType": "attachment",
                "contentType": "application/epub+zip",
                "linkMode": "imported_file",
            },
        },
        {
            "key": "SNAPSHOT",
            "data": {
                "itemType": "attachment",
                "contentType": "text/html",
                "linkMode": "imported_url",
            },
        },
        {
            "key": "OTHER",
            "data": {
                "itemType": "attachment",
                "contentType": "text/plain",
                "linkMode": "linked_url",
            },
        },
    ]
    api.children_results["PDF"] = [
        pdf_annotation,
        {"key": "PDF-NOTE", "data": {"itemType": "note"}},
    ]
    api.children_results["EPUB"] = [epub_annotation]
    api.children_results["SNAPSHOT"] = RuntimeError("children not supported")

    assert client.get_annotations_for_item("ITEM") == [
        pdf_annotation,
        epub_annotation,
    ]
    assert api.calls == [
        ("children", ("ITEM",), {}),
        ("everything", (api.children_results["ITEM"],), {}),
        ("children", ("PDF",), {}),
        ("everything", (api.children_results["PDF"],), {}),
        ("children", ("EPUB",), {}),
        ("everything", (api.children_results["EPUB"],), {}),
        ("children", ("SNAPSHOT",), {}),
    ]


def test_get_attachment_returns_first_pdf(patched_client):
    client, api, _ = patched_client
    first_pdf = {
        "key": "FIRST-PDF",
        "data": {"itemType": "attachment", "contentType": "application/pdf"},
    }
    api.children_results["ITEM"] = [
        {"key": "NOTE", "data": {"itemType": "note"}},
        {
            "key": "HTML",
            "data": {"itemType": "attachment", "contentType": "text/html"},
        },
        first_pdf,
        {
            "key": "SECOND-PDF",
            "data": {"itemType": "attachment", "contentType": "application/pdf"},
        },
    ]

    assert client.get_attachment_for_item("ITEM") is first_pdf
    assert api.calls == [
        ("children", ("ITEM",), {}),
        ("everything", (api.children_results["ITEM"],), {}),
    ]


def test_get_attachment_returns_none_without_pdf(patched_client):
    client, api, _ = patched_client
    api.children_results["ITEM"] = [
        {"key": "NOTE", "data": {"itemType": "note"}},
        {
            "key": "HTML",
            "data": {"itemType": "attachment", "contentType": "text/html"},
        },
    ]

    assert client.get_attachment_for_item("ITEM") is None
    assert api.calls == [
        ("children", ("ITEM",), {}),
        ("everything", (api.children_results["ITEM"],), {}),
    ]


def test_connection_reports_success(patched_client):
    client, api, _ = patched_client
    api.version = 12

    assert client.test_connection() is True
    assert api.calls == [("last_modified_version", (), {})]


def test_connection_reports_failure(patched_client):
    client, api, _ = patched_client
    api.failures["last_modified_version"] = ConnectionError("offline")

    assert client.test_connection() is False
    assert api.calls == [("last_modified_version", (), {})]


def test_full_read_workflow_never_invokes_a_write_like_pyzotero_method(
    patched_client,
):
    client, api, _ = patched_client
    direct_children: list[dict] = []
    annotation_children: list[dict] = []
    attachment_children: list[dict] = []
    api.children_results.update(
        {
            "DIRECT": direct_children,
            "ANNOTATIONS": annotation_children,
            "ATTACHMENT": attachment_children,
        }
    )

    client.get_library_version()
    client.get_all_items(3)
    client.get_items_since_version(2, 4)
    client.get_item_children("DIRECT")
    client.get_annotations_for_item("ANNOTATIONS")
    client.get_all_annotations(5)
    client.get_all_attachments(6)
    client.get_deleted_items(7)
    client.get_attachment_for_item("ATTACHMENT")
    client.test_connection()

    assert api.calls == [
        ("last_modified_version", (), {}),
        ("top", (), {"limit": 3, "includeTrashed": 1}),
        ("everything", (api.top_result,), {}),
        ("top", (), {"limit": 4, "since": 2, "includeTrashed": 1}),
        ("everything", (api.top_result,), {}),
        ("children", ("DIRECT",), {}),
        ("everything", (direct_children,), {}),
        ("children", ("ANNOTATIONS",), {}),
        ("everything", (annotation_children,), {}),
        ("items", (), {"itemType": "annotation", "limit": 5}),
        ("everything", (api.items_result,), {}),
        ("items", (), {"itemType": "attachment", "limit": 6}),
        ("everything", (api.items_result,), {}),
        ("deleted", (), {"since": 7}),
        ("children", ("ATTACHMENT",), {}),
        ("everything", (attachment_children,), {}),
        ("last_modified_version", (), {}),
    ]
