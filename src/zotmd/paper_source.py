"""Read immutable paper snapshots from Zotero's local HTTP API."""

from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote_to_bytes, urlsplit

from .models.paper import (
    AttachmentAvailability,
    Creator,
    Diagnostic,
    Identifier,
    Paper,
    PdfAttachment,
    Tag,
    _inspect_local_file,
)
from .utils.citation_key import CitationKeyExtractor

_PAGE_SIZE = 100
_MAX_ATTEMPTS = 4
_STORED_MODES = {"imported_file", "imported_url"}
_LINKED_MODES = {"linked_file", "linked_url"}
_NON_BIBLIOGRAPHIC_TYPES = {"annotation", "attachment", "note"}
_VENUE_FIELDS = (
    "publicationTitle",
    "bookTitle",
    "proceedingsTitle",
    "conferenceName",
    "websiteTitle",
    "blogTitle",
    "forumTitle",
    "encyclopediaTitle",
    "dictionaryTitle",
    "repository",
    "university",
    "institution",
    "meetingName",
    "company",
)
_VERSION_PATTERN = re.compile(r"[0-9]+")
_ITEM_KEY_PATTERN = re.compile(r"[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}")
_MD5_PATTERN = re.compile(r"[0-9a-fA-F]{32}")
_DOI_PATTERN = re.compile(r"10\.[0-9]{4,9}/\S+", re.IGNORECASE)
_ARXIV_PATTERN = re.compile(
    r"(?:[0-9]{4}\.[0-9]{4,5}|[a-z][a-z0-9.-]*/[0-9]{7})(?:v[0-9]+)?",
    re.IGNORECASE,
)
_EXTRA_DOI_PATTERN = re.compile(r"^\s*DOI\s*:\s*(.*?)\s*$", re.IGNORECASE)
_EXTRA_ARXIV_PATTERN = re.compile(r"^\s*arXiv\s*:\s*(.*?)\s*$", re.IGNORECASE)


class _PaginationChanged(ValueError):
    pass


class _LocalPaperClient:
    """Narrow, read-only adapter over a local-mode Pyzotero client."""

    def __init__(self) -> None:
        import httpx2
        from pyzotero import Zotero
        from pyzotero import __version__ as pyzotero_version

        http_client = httpx2.Client(
            headers={
                "User-Agent": f"Pyzotero/{pyzotero_version}",
                "Zotero-API-Version": "3",
            },
            follow_redirects=False,
            timeout=30,
            trust_env=False,
        )
        try:
            self._zot = Zotero(
                library_id="0",
                library_type="user",
                api_key=None,
                local=True,
                client=http_client,
                server_id=None,
                local_api_key=None,
            )
        except BaseException:
            http_client.close()
            raise
        if self._zot.client is None:
            http_client.close()
            raise RuntimeError("Pyzotero did not construct an HTTP client")

    def _response_server_id(self, expected: str | None = None) -> str:
        response = self._zot.request
        if response is None:
            raise ValueError("Local API response was not captured")
        server_id = response.headers.get("zotero-server-id", "").strip()
        if not server_id:
            raise ValueError("Local API response has no Zotero-Server-ID")
        captured = self._zot.server_id
        if not isinstance(captured, str) or not captured.strip():
            raise ValueError("Pyzotero did not capture the Zotero-Server-ID")
        if captured != server_id or (expected is not None and server_id != expected):
            raise ValueError("Local API server identity changed during the snapshot")
        return server_id

    def library_version(self, expected_server_id: str | None = None) -> tuple[int, str]:
        self._zot.last_modified_version()
        response = self._zot.request
        if response is None:
            raise ValueError("Local API version response was not captured")
        raw_version = response.headers.get("last-modified-version")
        if raw_version is None or _VERSION_PATTERN.fullmatch(raw_version) is None:
            raise ValueError("Local API response has no valid Last-Modified-Version")
        server_id = self._response_server_id(expected_server_id)
        return int(raw_version), server_id

    def _materialize_pages(
        self,
        first_page: object,
        expected_server_id: str,
        *,
        expected_path: str,
        expected_params: dict[str, str],
    ) -> tuple[dict[str, Any], ...]:
        records: list[dict[str, Any]] = []
        page = first_page
        expected_total: int | None = None
        while True:
            self._response_server_id(expected_server_id)
            if not isinstance(page, list) or not all(
                isinstance(record, dict) for record in page
            ):
                raise ValueError("Local API returned an invalid item-list envelope")
            response = self._zot.request
            if response is None:
                raise ValueError("Local API response was not captured")
            raw_total = response.headers.get("total-results")
            if raw_total is None or _VERSION_PATTERN.fullmatch(raw_total) is None:
                raise ValueError("Local API response has no valid Total-Results")
            page_total = int(raw_total)
            if expected_total is None:
                expected_total = page_total
            elif page_total != expected_total:
                raise _PaginationChanged("Local API pagination changed Total-Results")
            if len(records) + len(page) > expected_total:
                raise ValueError("Local API pagination exceeded Total-Results")
            records.extend(page)
            links = self._zot.links
            if not isinstance(links, dict) or not links.get("next"):
                if len(records) != expected_total:
                    raise ValueError("Local API pagination ended before Total-Results")
                return tuple(records)
            if not page:
                raise ValueError(
                    "Local API pagination returned an empty intermediate page"
                )
            next_link = links["next"]
            if not isinstance(next_link, str):
                raise ValueError("Local API returned an unsafe pagination target")
            next_url = urlsplit(next_link)
            next_params = parse_qs(next_url.query, keep_blank_values=True)
            allowed_params = {*expected_params, "format", "locale", "start"}
            if (
                next_url.scheme
                or next_url.netloc
                or next_url.fragment
                or next_url.path != expected_path
                or set(next_params) - allowed_params
                or any(
                    next_params.get(name) != [value]
                    for name, value in expected_params.items()
                )
                or ("format" in next_params and next_params["format"] != ["json"])
                or ("locale" in next_params and len(next_params["locale"]) != 1)
                or "start" not in next_params
                or len(next_params["start"]) != 1
                or _VERSION_PATTERN.fullmatch(next_params["start"][0]) is None
            ):
                raise ValueError("Local API returned an unsafe pagination target")
            next_start = int(next_params["start"][0])
            if next_start != len(records):
                raise ValueError("Local API pagination was not contiguous")
            page = self._zot.follow()

    def tagged_top_items(
        self, tag: str, expected_server_id: str
    ) -> tuple[dict[str, Any], ...]:
        first_page = self._zot.top(
            tag=tag,
            limit=_PAGE_SIZE,
            includeTrashed=0,
        )
        return self._materialize_pages(
            first_page,
            expected_server_id,
            expected_path="/api/users/0/items/top",
            expected_params={
                "tag": tag,
                "limit": str(_PAGE_SIZE),
                "includeTrashed": "0",
            },
        )

    def children(
        self, item_key: str, expected_server_id: str
    ) -> tuple[dict[str, Any], ...]:
        first_page = self._zot.children(
            item_key,
            limit=_PAGE_SIZE,
            includeTrashed=0,
            itemType="attachment",
        )
        return self._materialize_pages(
            first_page,
            expected_server_id,
            expected_path=f"/api/users/0/items/{item_key}/children",
            expected_params={
                "limit": str(_PAGE_SIZE),
                "includeTrashed": "0",
                "itemType": "attachment",
            },
        )

    def file_url(self, attachment_key: str, expected_server_id: str) -> str:
        path = f"/users/0/items/{quote(attachment_key, safe='')}/file/view/url"
        response = self._zot._retrieve_data(path)
        self._response_server_id(expected_server_id)
        if response.status_code != 200:
            raise ValueError("Local API file URL endpoint returned an invalid response")
        file_url = response.text.strip()
        if not file_url:
            raise ValueError("Local API file URL endpoint returned an empty response")
        return file_url

    def close(self) -> None:
        if self._zot.client is not None:
            self._zot.client.close()


def _validate_tag(tag: str) -> None:
    if not isinstance(tag, str):
        raise TypeError("tag must be a string")
    if not tag.strip():
        raise ValueError("tag must be nonblank")
    if tag.startswith("-"):
        raise ValueError("tag cannot use Zotero's negation syntax")
    if any(unicodedata.category(character) == "Cc" for character in tag):
        raise ValueError("tag cannot contain control characters")


def _library_identity(item: dict[str, Any]) -> tuple[str, int]:
    library = item.get("library")
    if not isinstance(library, dict) or library.get("type") != "user":
        raise ValueError("Local API item has an invalid library identity")
    library_id = library.get("id")
    if isinstance(library_id, bool):
        raise ValueError("Local API item has an invalid library ID")
    if isinstance(library_id, str) and library_id.isdecimal():
        library_id = int(library_id)
    if not isinstance(library_id, int) or library_id < 0:
        raise ValueError("Local API item has an invalid library ID")
    return "user", library_id


def _validate_item(
    item: object,
    *,
    expected_parent: str | None,
    expected_library: tuple[str, int] | None,
    seen_keys: set[str],
) -> tuple[dict[str, Any], tuple[str, int], str, int]:
    if not isinstance(item, dict):
        raise ValueError("Local API returned a non-object item")
    key = item.get("key")
    if not isinstance(key, str) or _ITEM_KEY_PATTERN.fullmatch(key) is None:
        raise ValueError("Local API item has no canonical key")
    if key in seen_keys:
        raise ValueError(f"Local API returned duplicate item key {key}")

    version = item.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError(f"Local API item {key} has an invalid local version")
    data = item.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"Local API item {key} has no data object")
    if data.get("key") != key:
        raise ValueError(f"Local API item {key} has inconsistent nested identity")
    nested_version = data.get("version")
    if (
        isinstance(nested_version, bool)
        or not isinstance(nested_version, int)
        or nested_version != version
    ):
        raise ValueError(f"Local API item {key} has inconsistent nested version")
    if not isinstance(data.get("itemType"), str) or not data["itemType"].strip():
        raise ValueError(f"Local API item {key} has no valid item type")

    parent_key = data.get("parentItem")
    if expected_parent is None:
        if parent_key not in (None, ""):
            raise ValueError(f"Top-level item {key} has a parent identity")
    elif parent_key != expected_parent:
        raise ValueError(f"Local API child {key} has the wrong parent identity")

    library = _library_identity(item)
    if expected_library is not None and library != expected_library:
        raise ValueError(f"Local API item {key} has inconsistent library identity")
    seen_keys.add(key)
    return data, library, key, version


def _has_exact_manual_tag(data: dict[str, Any], selected_tag: str) -> bool:
    tags = data.get("tags")
    if not isinstance(tags, list):
        return False
    for tag in tags:
        if not isinstance(tag, dict) or tag.get("tag") != selected_tag:
            continue
        tag_type = tag.get("type", 0)
        if (
            isinstance(tag_type, int)
            and not isinstance(tag_type, bool)
            and tag_type == 0
        ):
            return True
    return False


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _parse_creators(data: dict[str, Any]) -> tuple[Creator, ...]:
    raw_creators = data.get("creators")
    if not isinstance(raw_creators, list):
        return ()
    creators = []
    for raw_creator in raw_creators:
        if not isinstance(raw_creator, dict):
            continue
        creator_type = raw_creator.get("creatorType")
        creators.append(
            Creator(
                creator_type=creator_type if isinstance(creator_type, str) else "",
                first_name=(
                    raw_creator.get("firstName")
                    if isinstance(raw_creator.get("firstName"), str)
                    else None
                ),
                last_name=(
                    raw_creator.get("lastName")
                    if isinstance(raw_creator.get("lastName"), str)
                    else None
                ),
                name=(
                    raw_creator.get("name")
                    if isinstance(raw_creator.get("name"), str)
                    else None
                ),
            )
        )
    return tuple(creators)


def _parse_tags(data: dict[str, Any]) -> tuple[Tag, ...]:
    raw_tags = data.get("tags")
    if not isinstance(raw_tags, list):
        return ()
    tags = []
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, dict) or not isinstance(raw_tag.get("tag"), str):
            continue
        tag_type = raw_tag.get("type", 0)
        if isinstance(tag_type, bool) or not isinstance(tag_type, int):
            continue
        tags.append(Tag(name=raw_tag["tag"], type=tag_type))
    return tuple(tags)


def _normalize_doi(raw: str) -> str | None:
    value = raw.strip()
    value = re.sub(
        r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = unicodedata.normalize("NFKC", value).casefold()
    if _DOI_PATTERN.fullmatch(value) is None or any(
        character.isspace() for character in value
    ):
        return None
    return value


def _normalize_arxiv(raw: str) -> tuple[str | None, tuple[str, ...]]:
    value = raw.strip()
    value = re.sub(r"^arxiv\s*:\s*", "", value, count=1, flags=re.IGNORECASE)
    value = re.sub(
        r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\.pdf$", "", value, count=1, flags=re.IGNORECASE)
    value = unicodedata.normalize("NFKC", value).casefold()
    if _ARXIV_PATTERN.fullmatch(value) is None:
        return None, ()
    base = re.sub(r"v[0-9]+$", "", value, flags=re.IGNORECASE)
    aliases = (base,) if base != value else ()
    return value, aliases


def _parse_identifiers(
    data: dict[str, Any], item_key: str
) -> tuple[tuple[Identifier, ...], tuple[Diagnostic, ...]]:
    identifiers: list[Identifier] = []
    diagnostics: list[Diagnostic] = []

    direct_doi = _optional_string(data.get("DOI"))
    if direct_doi is not None:
        normalized = _normalize_doi(direct_doi)
        identifiers.append(Identifier("doi", direct_doi, normalized, source="field"))
        if normalized is None:
            diagnostics.append(
                Diagnostic(
                    "invalid-doi",
                    f"Item {item_key} has an invalid DOI field",
                    False,
                )
            )

    extra = data.get("extra")
    extra_lines = extra.splitlines() if isinstance(extra, str) else []
    for line in extra_lines:
        match = _EXTRA_DOI_PATTERN.fullmatch(line)
        if match is None or not match.group(1):
            continue
        raw = match.group(1)
        normalized = _normalize_doi(raw)
        if any(
            identifier.kind == "doi"
            and identifier.normalized is not None
            and identifier.normalized == normalized
            for identifier in identifiers
        ):
            continue
        identifiers.append(Identifier("doi", raw, normalized, source="extra"))
        if normalized is None:
            diagnostics.append(
                Diagnostic(
                    "invalid-doi",
                    f"Item {item_key} has an invalid structured DOI",
                    False,
                )
            )
        elif direct_doi is not None and _normalize_doi(direct_doi) not in (
            None,
            normalized,
        ):
            diagnostics.append(
                Diagnostic(
                    "conflicting-doi",
                    f"Item {item_key} has conflicting valid DOI values",
                    False,
                )
            )

    archive = _optional_string(data.get("archive"))
    archive_id = _optional_string(data.get("archiveLocation"))
    if (
        archive is not None
        and archive.strip().casefold() == "arxiv"
        and archive_id is not None
    ):
        normalized, aliases = _normalize_arxiv(archive_id)
        identifiers.append(
            Identifier("arxiv", archive_id, normalized, aliases, source="field")
        )
        if normalized is None:
            diagnostics.append(
                Diagnostic(
                    "invalid-arxiv",
                    f"Item {item_key} has an invalid arXiv archive identifier",
                    False,
                )
            )

    for line in extra_lines:
        match = _EXTRA_ARXIV_PATTERN.fullmatch(line)
        if match is None or not match.group(1):
            continue
        raw = match.group(1)
        normalized, aliases = _normalize_arxiv(raw)
        if any(
            identifier.kind == "arxiv"
            and identifier.normalized is not None
            and identifier.normalized == normalized
            for identifier in identifiers
        ):
            continue
        identifiers.append(
            Identifier("arxiv", raw, normalized, aliases, source="extra")
        )
        if normalized is None:
            diagnostics.append(
                Diagnostic(
                    "invalid-arxiv",
                    f"Item {item_key} has an invalid structured arXiv identifier",
                    False,
                )
            )

    return tuple(identifiers), tuple(diagnostics)


def _file_uri_to_path(uri: str) -> Path:
    if re.search(r"%(?![0-9A-Fa-f]{2})", uri):
        raise ValueError("Malformed percent escape")
    parsed = urlsplit(uri)
    if (
        parsed.scheme.casefold() != "file"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname not in (None, "", "localhost")
    ):
        raise ValueError("Not a safe local file URI")
    try:
        decoded_path = unquote_to_bytes(parsed.path).decode(
            sys.getfilesystemencoding(), errors="strict"
        )
    except UnicodeDecodeError as error:
        raise ValueError("File URI contains malformed path bytes") from error
    if "\x00" in decoded_path:
        raise ValueError("File URI contains NUL")
    path = Path(decoded_path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("File URI path is not absolute and safe")
    return path


def _attachment_diagnostic(code: str, key: str) -> Diagnostic:
    messages = {
        "empty-local-file": "is empty",
        "invalid-enclosure-uri": "has an invalid local enclosure URI",
        "invalid-local-file": "could not be inspected safely",
        "invalid-zotero-md5": "has an invalid Zotero MD5 value",
        "linked-attachment": "uses a linked attachment mode",
        "local-file-unavailable": "is not available as a local file",
        "mime-extension-mismatch": "has conflicting PDF MIME and filename signals",
        "not-regular-file": "does not resolve to a regular file",
        "symlink-local-path": "resolves through a symbolic link",
        "unreadable-local-file": "is not readable",
        "unsafe-local-path": "has an unsafe local path",
        "unsupported-link-mode": "uses an unsupported attachment mode",
        "changed-local-file": "changed while it was inspected",
    }
    return Diagnostic(code, f"Attachment {key} {messages[code]}", True)


def _parse_attachment(
    item: dict[str, Any],
    data: dict[str, Any],
    key: str,
    version: int,
    parent_key: str,
    client: _LocalPaperClient,
    server_id: str,
) -> PdfAttachment | None:
    content_type = _optional_string(data.get("contentType"))
    filename = _optional_string(data.get("filename"))
    mime_pdf = (
        content_type.split(";", 1)[0].strip().casefold() == "application/pdf"
        if content_type is not None
        else False
    )
    extension_pdf = filename.casefold().endswith(".pdf") if filename else False
    if not mime_pdf and not extension_pdf:
        return None

    link_mode = _optional_string(data.get("linkMode"))
    diagnostics: list[Diagnostic] = []
    if mime_pdf != extension_pdf:
        diagnostics.append(_attachment_diagnostic("mime-extension-mismatch", key))

    raw_md5 = data.get("md5")
    zotero_md5 = raw_md5 if isinstance(raw_md5, str) else None
    if raw_md5 is not None and (
        not isinstance(raw_md5, str) or _MD5_PATTERN.fullmatch(raw_md5) is None
    ):
        diagnostics.append(_attachment_diagnostic("invalid-zotero-md5", key))

    raw_mtime = data.get("mtime")
    zotero_mtime = (
        raw_mtime
        if isinstance(raw_mtime, int) and not isinstance(raw_mtime, bool)
        else None
    )
    links = item.get("links")
    enclosure = links.get("enclosure") if isinstance(links, dict) else None
    enclosure_uri = (
        enclosure.get("href")
        if isinstance(enclosure, dict) and isinstance(enclosure.get("href"), str)
        else None
    )

    availability = AttachmentAvailability.INVALID
    path = None
    file_stat = None
    if link_mode in _LINKED_MODES:
        availability = AttachmentAvailability.LINKED
        diagnostics.append(_attachment_diagnostic("linked-attachment", key))
    elif link_mode not in _STORED_MODES:
        availability = AttachmentAvailability.UNSUPPORTED
        diagnostics.append(_attachment_diagnostic("unsupported-link-mode", key))
    elif diagnostics:
        availability = AttachmentAvailability.INVALID
    else:
        if enclosure_uri is None:
            enclosure_uri = client.file_url(key, server_id)
        try:
            path = _file_uri_to_path(enclosure_uri)
        except (TypeError, ValueError):
            diagnostics.append(_attachment_diagnostic("invalid-enclosure-uri", key))
        else:
            file_stat, problem = _inspect_local_file(path)
            if problem is None:
                availability = AttachmentAvailability.AVAILABLE
            else:
                diagnostics.append(_attachment_diagnostic(problem, key))
                availability = (
                    AttachmentAvailability.UNAVAILABLE
                    if problem == "local-file-unavailable"
                    else AttachmentAvailability.INVALID
                )

    return PdfAttachment(
        key=key,
        version=version,
        parent_key=parent_key,
        title=_optional_string(data.get("title")),
        filename=filename,
        content_type=content_type,
        link_mode=link_mode,
        enclosure_uri=enclosure_uri,
        zotero_md5=zotero_md5,
        zotero_mtime=zotero_mtime,
        path=path,
        local_size=file_stat.st_size if file_stat is not None else None,
        local_mtime_ns=file_stat.st_mtime_ns if file_stat is not None else None,
        local_device=file_stat.st_dev if file_stat is not None else None,
        local_inode=file_stat.st_ino if file_stat is not None else None,
        availability=availability,
        diagnostics=tuple(diagnostics),
    )


def _parse_paper(
    *,
    item: dict[str, Any],
    data: dict[str, Any],
    key: str,
    version: int,
    library: tuple[str, int],
    children: tuple[tuple[dict[str, Any], dict[str, Any], str, int], ...],
    client: _LocalPaperClient,
    server_id: str,
) -> Paper:
    diagnostics: list[Diagnostic] = []
    item_type = _optional_string(data.get("itemType")) or "unknown"
    if item_type in _NON_BIBLIOGRAPHIC_TYPES:
        diagnostics.append(
            Diagnostic(
                "unsupported-top-level-item",
                f"Item {key} is not a supported bibliographic item",
                True,
            )
        )

    title = _optional_string(data.get("title"))
    if title is None:
        diagnostics.append(
            Diagnostic("missing-title", f"Item {key} has no title", True)
        )
    citation_key = CitationKeyExtractor.extract(item)
    if citation_key is None:
        diagnostics.append(
            Diagnostic(
                "missing-citation-key",
                f"Item {key} has no citation key",
                True,
            )
        )
    elif not CitationKeyExtractor.validate(citation_key):
        diagnostics.append(
            Diagnostic(
                "invalid-citation-key",
                f"Item {key} has an unsafe citation key",
                True,
            )
        )

    identifiers, identifier_diagnostics = _parse_identifiers(data, key)
    diagnostics.extend(identifier_diagnostics)

    attachments = []
    for child_item, child_data, child_key, child_version in children:
        if child_data.get("itemType") != "attachment":
            continue
        attachment = _parse_attachment(
            child_item,
            child_data,
            child_key,
            child_version,
            key,
            client,
            server_id,
        )
        if attachment is not None:
            attachments.append(attachment)
    attachments.sort(key=lambda attachment: attachment.key)
    if len(attachments) > 1:
        diagnostics.append(
            Diagnostic(
                "multiple-pdf-candidates",
                f"Item {key} has multiple PDF candidates",
                True,
            )
        )

    venues = tuple(
        (field, value)
        for field in _VENUE_FIELDS
        if (value := _optional_string(data.get(field))) is not None
    )
    raw_collections = data.get("collections")
    collection_keys = (
        tuple(
            collection
            for collection in raw_collections
            if isinstance(collection, str) and collection
        )
        if isinstance(raw_collections, list)
        else ()
    )

    return Paper(
        server_id=server_id,
        library_type=library[0],
        library_id=library[1],
        key=key,
        version=version,
        item_type=item_type,
        citation_key=citation_key,
        title=title,
        creators=_parse_creators(data),
        publication_date=_optional_string(data.get("date")),
        venues=venues,
        venue=venues[0][1] if venues else None,
        url=_optional_string(data.get("url")),
        tags=_parse_tags(data),
        collection_keys=collection_keys,
        identifiers=identifiers,
        pdf_attachments=tuple(attachments),
        diagnostics=tuple(diagnostics),
    )


def _read_snapshot(client: _LocalPaperClient, tag: str) -> tuple[Paper, ...]:
    known_server_id: str | None = None
    for _attempt in range(_MAX_ATTEMPTS):
        start_version, server_id = client.library_version(known_server_id)
        known_server_id = server_id
        try:
            raw_top_items = client.tagged_top_items(tag, server_id)
        except _PaginationChanged:
            end_version, _end_server_id = client.library_version(server_id)
            if end_version != start_version:
                continue
            raise ValueError(
                "Local API pagination changed within a stable library version"
            ) from None

        seen_keys: set[str] = set()
        highest_item_version = 0
        library: tuple[str, int] | None = None
        selected: list[tuple[dict[str, Any], dict[str, Any], str, int]] = []
        for raw_item in raw_top_items:
            data, item_library, key, version = _validate_item(
                raw_item,
                expected_parent=None,
                expected_library=library,
                seen_keys=seen_keys,
            )
            if library is None:
                library = item_library
            highest_item_version = max(highest_item_version, version)
            if _has_exact_manual_tag(data, tag):
                selected.append((raw_item, data, key, version))

        child_sets = []
        unstable_pagination = False
        for _item, _data, parent_key, _version in selected:
            children = []
            try:
                raw_children = client.children(parent_key, server_id)
            except _PaginationChanged:
                end_version, _end_server_id = client.library_version(server_id)
                if end_version != start_version:
                    unstable_pagination = True
                    break
                raise ValueError(
                    "Local API pagination changed within a stable library version"
                ) from None
            for raw_child in raw_children:
                child_data, child_library, child_key, child_version = _validate_item(
                    raw_child,
                    expected_parent=parent_key,
                    expected_library=library,
                    seen_keys=seen_keys,
                )
                if library is None:
                    library = child_library
                highest_item_version = max(highest_item_version, child_version)
                children.append((raw_child, child_data, child_key, child_version))
            child_sets.append(tuple(children))
        if unstable_pagination:
            continue

        if library is None:
            papers: tuple[Paper, ...] = ()
        else:
            papers = tuple(
                _parse_paper(
                    item=item,
                    data=data,
                    key=key,
                    version=version,
                    library=library,
                    children=children,
                    client=client,
                    server_id=server_id,
                )
                for (item, data, key, version), children in zip(
                    selected, child_sets, strict=True
                )
            )

        end_version, end_server_id = client.library_version(server_id)
        if end_server_id == server_id and end_version == start_version:
            if highest_item_version > start_version:
                raise ValueError(
                    "Local API item version exceeds the stable library version"
                )
            return tuple(
                sorted(
                    papers,
                    key=lambda paper: (
                        paper.server_id,
                        paper.library_type,
                        paper.library_id,
                        paper.key,
                    ),
                )
            )

    raise RuntimeError("Zotero library changed during four snapshot attempts")


def iter_papers(*, tag: str) -> Iterator[Paper]:
    """Return an iterator over one complete stable local Zotero snapshot."""
    _validate_tag(tag)
    client = _LocalPaperClient()
    try:
        snapshot = _read_snapshot(client, tag)
    finally:
        client.close()
    return iter(snapshot)


__all__ = ["iter_papers"]
