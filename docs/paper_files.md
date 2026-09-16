# PDFs, diagnostics, and failures

Reference for PDF selection, file validation, diagnostic codes, snapshot retries, and exceptions.

## PDF candidates

An attachment is a PDF candidate when:

- MIME type is `application/pdf`, or
- filename ends in `.pdf`, case-insensitively

Both signals must agree before use.

Supported stored modes:

- `imported_file`
- `imported_url`

Linked and unknown modes remain visible but are ineligible. ZotMD never resolves or inspects a linked path.

## Availability

| Value | Meaning |
|---|---|
| `available` | Readable, nonempty, regular local file; no-follow inspection passed |
| `unavailable` | Expected stored file is not local, including an on-demand WebDAV file |
| `linked` | Linked file or URL; path not inspected |
| `unsupported` | Unknown attachment mode |
| `invalid` | Unsafe URL, PDF signals, MD5 metadata, path, or local file |

`primary_pdf` returns the only candidate when the paper and attachment have no blocking diagnostic and the file is available. A second candidate is ambiguous even when unavailable or linked.

## Fingerprints

`fingerprint()` performs a fresh validated read on every call:

1. Reopen the path without following any component symlink.
2. Verify device, inode, size, and nanosecond modification time.
3. Stream the file once while calculating SHA-256 and MD5.
4. Verify the same file identity after the read.
5. Compare Zotero's MD5 when supplied.

Result:

```python
FileFingerprint(sha256, md5, size, mtime_ns, device, inode)
```

Fingerprint again before accepting later work when source changes matter.

## Paper diagnostics

| Code | Blocking | Condition |
|---|---|---|
| `missing-title` | Yes | Blank top-level title |
| `missing-citation-key` | Yes | No native or structured `Extra` key |
| `invalid-citation-key` | Yes | Unsafe selected key |
| `unsupported-top-level-item` | Yes | Tagged note, attachment, annotation, or other unsupported item |
| `multiple-pdf-candidates` | Yes | More than one PDF candidate |
| `invalid-doi` | No | DOI does not normalize |
| `conflicting-doi` | No | Dedicated and structured DOI values disagree |
| `invalid-arxiv` | No | arXiv value does not normalize |

## Attachment diagnostics

All attachment diagnostics block use.

| Code | Condition |
|---|---|
| `mime-extension-mismatch` | MIME type and filename extension disagree |
| `invalid-zotero-md5` | Zotero MD5 is not 32 hexadecimal characters |
| `linked-attachment` | Mode is `linked_file` or `linked_url` |
| `unsupported-link-mode` | Attachment mode is unknown |
| `invalid-enclosure-uri` | Enclosure is not a safe absolute local `file://` URI |
| `local-file-unavailable` | Expected stored file is not local |
| `symlink-local-path` | A path component is a symbolic link |
| `not-regular-file` | Target is not a regular file |
| `empty-local-file` | Target file is empty |
| `unreadable-local-file` | Target cannot be opened for reading |
| `unsafe-local-path` | Decoded path is not absolute and traversal-free |
| `changed-local-file` | File identity changed during discovery |
| `invalid-local-file` | Another safe inspection failed |

Messages may include Zotero item or attachment keys. They omit titles, creators, enclosure URLs, and local paths.

## Snapshot and ordering

ZotMD reads:

1. Starting library version and Zotero server ID
2. Every selected top-level page
3. Each selected item's child pages, serially
4. Eligible stored enclosure paths
5. Ending library version and server ID

The start and end values must match. A changed library triggers up to three complete retries after the initial attempt. A fourth unstable result raises `RuntimeError`; no partial iterator escapes.

Ordering:

- Papers: server ID, library type, library ID, item key
- PDF candidates: attachment key

## Exceptions

- Invalid arguments or malformed snapshots: `TypeError` or `ValueError`
- Four unstable snapshots: `RuntimeError`
- Changed file during hashing: `OSError`
- Zotero MD5 mismatch: `ValueError`
- Connection, HTTP, disabled-local-API, and server-ID failures: underlying Pyzotero or HTTP client exception

## Data limits

Paper discovery uses loopback GET requests only. It does not:

- Load `config.toml` or `sync.sqlite`
- Run synchronization
- Read generated notes
- Retain note or annotation content
- Call the Zotero Web API
- Authenticate to WebDAV
- Download files
- Request local write access

Keep Zotero's unauthenticated local API on port 23119 bound to the local machine. Do not forward or publicly expose it.
