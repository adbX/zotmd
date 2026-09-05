"""Data model for Zotero library items."""

import re
from dataclasses import dataclass, field
from datetime import datetime

from ..utils.citation_key import CitationKeyExtractor
from ..utils.date_formatter import DateFormatter

VENUE_FIELDS = (
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
    "publisher",
)
_TITLE_LINE_BREAK_PATTERN = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")


def normalize_title(title: object) -> str:
    """Return a nonblank publication title with every line break replaced."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Publication title must be a nonblank string")
    return _TITLE_LINE_BREAK_PATTERN.sub(" ", title)


@dataclass
class ZoteroItem:
    """Represents a Zotero library item with all relevant metadata."""

    # Core identifiers
    key: str
    version: int
    item_type: str
    citation_key: str

    # Metadata
    title: str
    creators: list[dict] = field(default_factory=list)
    date: str | None = None
    date_added: datetime | None = None
    date_modified: datetime | None = None

    # Content
    abstract: str | None = None
    tags: list[str] = field(default_factory=list)

    # Links and identifiers
    doi: str | None = None
    url: str | None = None
    pdf_link: str | None = None  # zotero://select/library/items/XXX

    # Additional metadata
    publication_title: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    venue: str | None = None

    # Related items
    collections: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)

    # Extra fields
    extra: str | None = None

    # Summary from meta
    creator_summary: str | None = None
    num_children: int = 0

    @classmethod
    def from_api_response(cls, item: dict, library_id: str) -> "ZoteroItem | None":
        """
        Parse Zotero API response into ZoteroItem model.

        Args:
            item: Zotero API item dictionary
            library_id: Zotero library ID for constructing links

        Returns:
            ZoteroItem instance or None if citation key is missing

        Example:
            >>> item = {
            ...     'key': 'ABC123',
            ...     'version': 100,
            ...     'data': {
            ...         'key': 'ABC123',
            ...         'itemType': 'journalArticle',
            ...         'title': 'Test Article',
            ...         'extra': 'Citation Key: test2020',
            ...         'creators': [{'firstName': 'John', 'lastName': 'Doe'}],
            ...         'dateAdded': '2025-12-21T10:00:00Z',
            ...     },
            ...     'meta': {'numChildren': 2}
            ... }
            >>> parsed = ZoteroItem.from_api_response(item, '123456')
            >>> parsed.citation_key
            'test2020'
        """
        try:
            data = item.get("data", {})
            meta = item.get("meta", {})

            try:
                title = normalize_title(data.get("title"))
            except ValueError:
                return None

            # Extract citation key (required)
            citation_key = CitationKeyExtractor.extract(item)
            if not citation_key:
                return None

            # Extract dates
            date_added = DateFormatter.parse_zotero_date(data.get("dateAdded"))
            date_modified = DateFormatter.parse_zotero_date(data.get("dateModified"))

            # Automatic Zotero tags have type 1; only user-assigned tags are rendered.
            tags = [
                tag.get("tag", "")
                for tag in data.get("tags", [])
                if tag.get("tag") and tag.get("type") != 1
            ]

            venue = next(
                (data[field] for field in VENUE_FIELDS if data.get(field)), None
            )

            # Build PDF link
            item_key = data.get("key", "")
            pdf_link = f"zotero://select/library/items/{item_key}" if item_key else None

            return cls(
                key=item.get("key", ""),
                version=item.get("version", 0),
                item_type=data.get("itemType", "unknown"),
                citation_key=citation_key,
                # Metadata
                title=title,
                creators=data.get("creators", []),
                date=data.get("date"),
                date_added=date_added,
                date_modified=date_modified,
                # Content
                abstract=data.get("abstractNote"),
                tags=tags,
                # Links
                doi=data.get("DOI"),
                url=data.get("url"),
                pdf_link=pdf_link,
                # Publication info
                publication_title=data.get("publicationTitle"),
                volume=data.get("volume"),
                issue=data.get("issue"),
                pages=data.get("pages"),
                publisher=data.get("publisher"),
                venue=venue,
                # Related
                collections=data.get("collections", []),
                relations=(
                    list(data.get("relations", {}).values())
                    if isinstance(data.get("relations"), dict)
                    else []
                ),
                # Extra
                extra=data.get("extra"),
                # Meta
                creator_summary=meta.get("creatorSummary"),
                num_children=meta.get("numChildren", 0),
            )

        except (KeyError, TypeError, AttributeError):
            # Log error if needed, return None
            return None
