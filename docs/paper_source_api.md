# Paper records

Reference for the immutable records returned by [`iter_papers()`](paper_discovery.md).

## Public imports

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

All records are frozen dataclasses. Nested collections are tuples. No record retains a mutable API response or Pyzotero object.

## `Paper`

| Field | Type | Meaning |
|---|---|---|
| `server_id` | `str` | Zotero server identity that scopes local versions |
| `library_type` | `str` | `user` for the supported personal library |
| `library_id` | `int` | Personal-library ID reported by Zotero |
| `key` | `str` | Zotero item key |
| `version` | `int` | Server-scoped local item version |
| `item_type` | `str` | Zotero item type |
| `citation_key` | `str | None` | Native citation key, then structured `Extra` fallback |
| `title` | `str | None` | Zotero title |
| `creators` | `tuple[Creator, ...]` | Creators in Zotero order |
| `publication_date` | `str | None` | Raw Zotero publication date |
| `venues` | `tuple[tuple[str, str], ...]` | Populated supported venue fields and values |
| `venue` | `str | None` | First populated supported venue |
| `url` | `str | None` | Item URL |
| `tags` | `tuple[Tag, ...]` | Exact tag names and Zotero types |
| `collection_keys` | `tuple[str, ...]` | Zotero collection keys |
| `identifiers` | `tuple[Identifier, ...]` | DOI and arXiv values |
| `pdf_attachments` | `tuple[PdfAttachment, ...]` | PDF candidates ordered by attachment key |
| `diagnostics` | `tuple[Diagnostic, ...]` | Unresolved paper conditions |

Computed properties:

- `zotero_uri`: `zotero://select/library/items/<ITEM_KEY>`
- `primary_pdf`: the only available candidate when the paper and attachment have no blocking diagnostic

??? info "Venue priority"

    `publicationTitle`, `bookTitle`, `proceedingsTitle`, `conferenceName`, `websiteTitle`, `blogTitle`, `forumTitle`, `encyclopediaTitle`, `dictionaryTitle`, `repository`, `university`, `institution`, `meetingName`, and `company`

    `publisher` is not a venue in this API.

## `Creator`

Fields:

- `creator_type`
- `first_name`
- `last_name`
- `name`

`display_name` prefers the single-field `name`, then joins the two-field name without changing stored components.

## `Tag`

Fields:

- `name`
- Numeric `type`

Missing type becomes manual type `0`. Automatic type `1` cannot select a paper.

## `Identifier`

| Field | Value |
|---|---|
| `kind` | `doi` or `arxiv` |
| `raw` | Original Zotero value |
| `normalized` | Normalized value, or `None` when invalid |
| `aliases` | Alternate accepted values |
| `source` | `field` or `extra` |

Example: `2401.01234v2` stays versioned in `normalized` and adds `2401.01234` to `aliases`.

## `Diagnostic`

Fields:

- Stable `code`
- Path- and metadata-safe `message`
- Boolean `blocking`

Branch on `code`, not message text. See [PDFs, diagnostics, and failures](paper_files.md) for every code.

## `PdfAttachment`

Fields:

- Identity: `key`, `version`, `parent_key`
- Metadata: `title`, `filename`, `content_type`, `link_mode`
- Zotero file data: `enclosure_uri`, `zotero_md5`, `zotero_mtime`
- Local file data: `path`, `local_size`, `local_mtime_ns`, `local_device`, `local_inode`
- Result: `availability`, `diagnostics`

Object representations omit `enclosure_uri` and `path`.

## `FileFingerprint`

Fields:

- `sha256`
- `md5`
- `size`
- `mtime_ns`
- `device`
- `inode`

The result describes one completed validated read. See [PDFs, diagnostics, and failures](paper_files.md) for file eligibility and validation behavior.
