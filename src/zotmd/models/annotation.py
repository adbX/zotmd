"""Data model for Zotero annotations."""

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime

from ..utils.color_mapper import ColorMapper
from ..utils.date_formatter import DateFormatter


@dataclass
class Annotation:
    """Represents a Zotero annotation (highlight, note, or image)."""

    # Core identifiers
    key: str
    parent_key: str
    version: int

    # Annotation content
    annotation_type: str  # highlight, note, image
    text: str | None = None
    comment: str | None = None

    # Color information
    color_hex: str = "#aaaaaa"
    color_category: str = "gray"

    # Page information
    page_label: str | None = None
    page_index: int | None = None

    # Position data (JSON string)
    position: str | None = None

    # Timestamps
    date_added: datetime | None = None
    date_modified: datetime | None = None

    # Sort index for ordering
    sort_index: str | None = None

    @classmethod
    def from_api_response(cls, annotation: dict) -> "Annotation":
        """
        Parse Zotero API annotation response into Annotation model.

        Args:
            annotation: Zotero API annotation dictionary

        Returns:
            Annotation instance

        Example:
            >>> annot = {
            ...     'key': 'ANN123',
            ...     'version': 50,
            ...     'data': {
            ...         'key': 'ANN123',
            ...         'parentItem': 'ITEM123',
            ...         'annotationType': 'highlight',
            ...         'annotationText': 'Important text',
            ...         'annotationComment': 'My note',
            ...         'annotationColor': '#a28ae5',
            ...         'annotationPageLabel': '19',
            ...         'annotationPosition': '{"pageIndex":18}',
            ...         'dateAdded': '2025-12-21T11:05:00Z',
            ...     }
            ... }
            >>> parsed = Annotation.from_api_response(annot)
            >>> parsed.color_category
            'purple'
        """
        try:
            data = annotation.get("data", {})

            # Extract and map color
            color_hex = data.get("annotationColor", "#aaaaaa")
            color_category = ColorMapper.hex_to_category(color_hex)

            # Parse dates
            date_added = DateFormatter.parse_zotero_date(data.get("dateAdded"))
            date_modified = DateFormatter.parse_zotero_date(data.get("dateModified"))

            # Extract page index from position JSON
            page_index = None
            position_str = data.get("annotationPosition")
            if position_str:
                try:
                    position_data = json.loads(position_str)
                    page_index = position_data.get("pageIndex")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

            return cls(
                key=annotation.get("key", ""),
                parent_key=data.get("parentItem", ""),
                version=annotation.get("version", 0),
                annotation_type=data.get("annotationType", "note"),
                text=data.get("annotationText"),
                comment=data.get("annotationComment"),
                color_hex=color_hex,
                color_category=color_category,
                page_label=data.get("annotationPageLabel"),
                page_index=page_index,
                position=position_str,
                date_added=date_added,
                date_modified=date_modified,
                sort_index=data.get("annotationSortIndex"),
            )

        except (KeyError, TypeError, AttributeError):
            # Return minimal annotation on error
            return cls(
                key=annotation.get("key", "UNKNOWN"),
                parent_key="",
                version=0,
                annotation_type="note",
            )

    @staticmethod
    def _escape_source(value: str) -> str:
        escaped = html.escape(value, quote=True)
        return re.sub(r"\r\n?|\n", "<br>", escaped)

    def _page_link(self) -> str:
        page = f"Page {html.escape(self.page_label)}" if self.page_label else "Page ?"
        query = f"page={self.page_index}&" if self.page_index is not None else ""
        uri = (
            f"zotero://open-pdf/library/items/{self.parent_key}"
            f"?{query}annotation={self.key}"
        )
        return f"[{page}]({uri})"

    def to_markdown(self) -> str:
        """Render deterministic, HTML-safe Markdown for this annotation."""
        link = self._page_link()
        lines: list[str] = []

        if self.annotation_type == "image":
            lines.append(f"- Image annotation {link}")
            if self.comment:
                lines.append(f"  - {self._escape_source(self.comment)}")
        elif self.text:
            color = html.escape(self.color_category, quote=True)
            lines.append(
                f'- <mark class="hltr-{color}">{self._escape_source(self.text)}</mark> '
                f"{link}"
            )
            if self.comment:
                lines.append(f"  - {self._escape_source(self.comment)}")
        elif self.comment:
            lines.append(f"- {self._escape_source(self.comment)} {link}")

        return "\n".join(lines)

    def __lt__(self, other: "Annotation") -> bool:
        """
        Compare annotations for sorting.

        Sorts by:
        1. Page index (if available)
        2. Sort index (Zotero's internal ordering)
        3. Date added
        """
        if not isinstance(other, Annotation):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def _sort_key(self) -> tuple[bool, int, bool, str, bool, str, str]:
        return (
            self.page_index is None,
            self.page_index if self.page_index is not None else 0,
            self.sort_index is None,
            self.sort_index or "",
            self.date_added is None,
            self.date_added.isoformat() if self.date_added else "",
            self.key,
        )
