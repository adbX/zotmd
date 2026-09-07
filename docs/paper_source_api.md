# Local Paper-Source API

ZotMD exposes a read-only Python API for discovering papers and already-local PDFs in one personal Zotero 10 library. This API is separate from `zotmd sync`: it uses Zotero Desktop's loopback HTTP API, needs no Zotero Web API key or internet connection, and does not load ZotMD configuration or state.

This API is currently part of the unreleased 0.5 source and is not included in the latest PyPI package yet.

## Requirements

- Zotero 10 is running with **Settings > Advanced > Allow other applications on this computer to communicate with Zotero** enabled.
- The selected tag is one exact, nonblank manual tag on each top-level item.
- Zotero has already made any PDF to be processed available locally. ZotMD does not contact WebDAV or trigger a download.
- Port 23119 remains bound to the local machine. The local API is unauthenticated for reads, so do not forward or publicly expose this port.

## Example

```python
from zotmd import iter_papers

for paper in iter_papers(tag="paper-source"):
    attachment = paper.primary_pdf
    if attachment is None:
        continue
    fingerprint = attachment.fingerprint()
    print(paper.key, fingerprint.sha256)
```

`iter_papers()` finishes every Zotero request, validates the complete snapshot, closes its HTTP client, and only then returns an iterator. Accessing `primary_pdf`, representing records, and comparing records do not make the ZotMD process read PDF bytes. `fingerprint()` performs the first ZotMD file-content read and must succeed before another program receives the path. Zotero Desktop may perform its own unavoidable MD5 read while serializing local attachment metadata.

## Public Imports

The supported package-root imports are:

```python
from zotmd import (
    __version__,
    AttachmentAvailability,
    Creator,
    Diagnostic,
    FileFingerprint,
    Identifier,
    Paper,
    PdfAttachment,
    Tag,
    iter_papers,
)
```

All records are frozen dataclasses. Nested collections are tuples, and no record retains a mutable API response or Pyzotero object.

## Paper Records

`Paper` contains these fields:

| Field | Type | Meaning |
|---|---|---|
| `server_id` | `str` | Zotero server identity that scopes all local versions |
| `library_type` | `str` | `user` for the supported personal library |
| `library_id` | `int` | Personal-library identity reported by Zotero |
| `key` | `str` | Zotero item key |
| `version` | `int` | Server-scoped local item version |
| `item_type` | `str` | Zotero item type |
| `citation_key` | `str | None` | Native citation key, with structured `Extra` fallback |
| `title` | `str | None` | Zotero title |
| `creators` | `tuple[Creator, ...]` | Creators in Zotero order |
| `publication_date` | `str | None` | Raw Zotero publication date |
| `venues` | `tuple[tuple[str, str], ...]` | Every populated supported venue field and value, in provider order |
| `venue` | `str | None` | First populated supported venue |
| `url` | `str | None` | Item URL |
| `tags` | `tuple[Tag, ...]` | Exact tag names and Zotero types |
| `collection_keys` | `tuple[str, ...]` | Zotero collection keys |
| `identifiers` | `tuple[Identifier, ...]` | DOI and arXiv values |
| `pdf_attachments` | `tuple[PdfAttachment, ...]` | Every child PDF candidate, ordered by attachment key |
| `diagnostics` | `tuple[Diagnostic, ...]` | Unresolved paper conditions |

`zotero_uri` derives `zotero://select/library/items/<ITEM_KEY>`. `primary_pdf` returns the only PDF candidate when the paper and attachment have no blocking diagnostic and the file is currently available. Any second PDF candidate makes the result ambiguous, including an unavailable or linked candidate.

The venue order is `publicationTitle`, `bookTitle`, `proceedingsTitle`, `conferenceName`, `websiteTitle`, `blogTitle`, `forumTitle`, `encyclopediaTitle`, `dictionaryTitle`, `repository`, `university`, `institution`, `meetingName`, and `company`. `publisher` is not a venue in this API.

## Supporting Records

`Creator` retains `creator_type`, `first_name`, `last_name`, and single-field `name`. Its `display_name` property prefers `name`, then joins the two-field name without changing the stored components.

`Tag` contains `name` and numeric `type`. A missing Zotero type becomes manual type `0`; automatic type `1` cannot satisfy selection.

`Identifier` contains `kind`, `raw`, `normalized`, `aliases`, and `source`. `kind` is `doi` or `arxiv`, while `source` is `field` or `extra`. Invalid raw values remain visible with `normalized=None`. A versioned arXiv value such as `2401.01234v2` retains that normalized value and adds `2401.01234` to `aliases`.

`Diagnostic` contains a stable `code`, a path- and metadata-safe `message`, and `blocking`. Consumers should branch on `code`, not message text.

## PDF Records and Fingerprints

`PdfAttachment` retains `key`, `version`, `parent_key`, `title`, `filename`, `content_type`, `link_mode`, `enclosure_uri`, `zotero_md5`, `zotero_mtime`, `path`, `local_size`, `local_mtime_ns`, `local_device`, `local_inode`, `availability`, and `diagnostics`. Representations omit `enclosure_uri` and `path`.

An attachment is a PDF candidate when its normalized MIME type is `application/pdf` or its filename ends in `.pdf`, case-insensitively. Both signals must agree for conversion. `imported_file` and `imported_url` are the supported stored modes. Linked and unknown modes remain visible but are ineligible, and ZotMD never resolves or inspects a linked path.

`AttachmentAvailability` has five values:

| Value | Meaning |
|---|---|
| `available` | A readable, nonempty, regular local file passed no-follow inspection |
| `unavailable` | The expected stored file is not local, including an on-demand WebDAV file |
| `linked` | Zotero reports a linked file or URL; its path was not inspected |
| `unsupported` | Zotero reports an unknown attachment mode |
| `invalid` | The URL, PDF signals, MD5 metadata, path, or local file is unsafe |

`fingerprint()` reopens the path without following any component symlink. It verifies the discovered device, inode, size, and nanosecond modification time before and after one streaming read, calculates SHA-256 and MD5 together, then checks Zotero's MD5 when supplied. Each call performs a fresh validated read and returns `FileFingerprint(sha256, md5, size, mtime_ns, device, inode)`. The result describes that completed read; a consumer that delays file use or performs long-running work must fingerprint again before accepting its output if source changes matter.

## Diagnostics

Paper diagnostics are:

| Code | Blocking | Condition |
|---|---|---|
| `missing-title` | Yes | The top-level item has no nonblank title |
| `missing-citation-key` | Yes | Neither native metadata nor structured `Extra` supplies a key |
| `invalid-citation-key` | Yes | The selected key is unsafe |
| `unsupported-top-level-item` | Yes | A tagged top-level note, attachment, annotation, or other unsupported item was returned |
| `multiple-pdf-candidates` | Yes | The parent has more than one PDF candidate |
| `invalid-doi` | No | A retained DOI does not normalize to valid syntax |
| `conflicting-doi` | No | Valid dedicated and structured DOI values disagree |
| `invalid-arxiv` | No | A retained arXiv value does not normalize to valid syntax |

Attachment diagnostics are all blocking:

| Code | Condition |
|---|---|
| `mime-extension-mismatch` | MIME type and filename extension disagree about PDF format |
| `invalid-zotero-md5` | Zotero's MD5 value is not 32 hexadecimal characters |
| `linked-attachment` | The attachment uses `linked_file` or `linked_url` |
| `unsupported-link-mode` | The attachment mode is unknown |
| `invalid-enclosure-uri` | The enclosure is not a safe absolute local `file://` URI |
| `local-file-unavailable` | The expected stored file does not exist locally |
| `symlink-local-path` | Any existing path component is a symbolic link |
| `not-regular-file` | The target is not a regular file |
| `empty-local-file` | The target file is empty |
| `unreadable-local-file` | The target cannot be opened for reading |
| `unsafe-local-path` | The decoded path is not absolute and traversal-free |
| `changed-local-file` | The file identity changed during discovery |
| `invalid-local-file` | Another safe inspection failed |

Messages may include Zotero item or attachment keys. They never include titles, creators, enclosure URLs, or local paths.

## Snapshot and Ordering

The provider reads a starting local library version, materializes every top-level page, fetches each selected item's child pages serially, resolves eligible stored enclosure paths, then reads the ending version. It accepts the snapshot only when both versions and the Zotero server ID match.

If the library version changes, ZotMD discards all collected records and makes up to three complete retries after the initial attempt. A fourth unstable result raises `RuntimeError`; no partial iterator escapes. Papers are ordered by server ID, library type, library ID, and item key. PDF candidates are ordered by attachment key.

## Failures and Boundaries

Invalid call arguments and malformed snapshots raise built-in `TypeError` or `ValueError`. Four unstable attempts raise `RuntimeError`. A file that differs from its discovered identity or changes during hashing raises `OSError`; a Zotero MD5 mismatch raises `ValueError`. Connection, transport, status, disabled-local-API, and server-ID mismatch errors propagate from Pyzotero and its HTTP client.

Paper discovery performs only loopback GET requests for library versions, tagged top-level items, attachment children, and the conditional `/file/view/url` fallback. It does not load configuration, run synchronization, inspect `sync.sqlite`, retain or expose note or annotation content, call the Zotero Web API, authenticate to WebDAV, download files, or request local write authorization. Tagged top-level notes remain visible only as unsupported-item diagnostics; Zotero-native note children and ZotMD-generated Markdown notes are outside this version's API.
