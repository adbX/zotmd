"""Data model for Zotero library items."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..utils.citation_key import CitationKeyExtractor
from ..utils.date_formatter import DateFormatter


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
    date: Optional[str] = None
    date_added: Optional[datetime] = None
    date_modified: Optional[datetime] = None

    # Content
    abstract: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    # Links and identifiers
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_link: Optional[str] = None  # zotero://select/library/items/XXX

    # Additional metadata
    publication_title: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None

    # Related items
    collections: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)

    # Extra fields
    extra: Optional[str] = None

    # Summary from meta
    creator_summary: Optional[str] = None
    num_children: int = 0

    @classmethod
    def from_api_response(cls, item: dict, library_id: str) -> Optional["ZoteroItem"]:
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

            # Extract citation key (required)
            citation_key = CitationKeyExtractor.extract(item)
            if not citation_key:
                return None

            # Extract dates
            date_added = DateFormatter.parse_zotero_date(data.get("dateAdded"))
            date_modified = DateFormatter.parse_zotero_date(data.get("dateModified"))

            # Extract tags (convert from list of dicts to list of strings)
            tags = [
                tag.get("tag", "") for tag in data.get("tags", []) if tag.get("tag")
            ]

            # Build PDF link
            item_key = data.get("key", "")
            pdf_link = f"zotero://select/library/items/{item_key}" if item_key else None

            return cls(
                key=item.get("key", ""),
                version=item.get("version", 0),
                item_type=data.get("itemType", "unknown"),
                citation_key=citation_key,
                # Metadata
                title=data.get("title", "Untitled"),
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
