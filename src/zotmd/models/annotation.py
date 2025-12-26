"""Data model for Zotero annotations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json

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
    text: Optional[str] = None
    comment: Optional[str] = None

    # Color information
    color_hex: str = "#aaaaaa"
    color_category: str = "gray"

    # Page information
    page_label: Optional[str] = None
    page_index: Optional[int] = None

    # Position data (JSON string)
    position: Optional[str] = None

    # Timestamps
    date_added: Optional[datetime] = None
    date_modified: Optional[datetime] = None

    # Sort index for ordering
    sort_index: Optional[str] = None

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

    def to_markdown(self, attachment_key: Optional[str] = None) -> str:
        """
        Convert annotation to markdown format matching template.

        Args:
            attachment_key: Key of the PDF attachment (for zotero:// link)

        Returns:
            Markdown formatted annotation

        Examples:
            >>> annot = Annotation(
            ...     key='ABC',
            ...     parent_key='PARENT',
            ...     version=1,
            ...     annotation_type='highlight',
            ...     text='Important point',
            ...     comment='My thoughts',
            ...     color_category='red',
            ...     page_label='5',
            ...     page_index=4
            ... )
            >>> print(annot.to_markdown('PDF123'))
            - <mark class="hltr-red">"Important point"</mark> [Page 5](zotero://open-pdf/library/items/PDF123?page=4&annotation=ABC)
              - My thoughts
        """
        lines = []

        # Main annotation line (highlight text)
        if self.text:
            # Escape double quotes in text
            escaped_text = self.text.replace('"', '\\"')

            # Build Zotero link
            link_parts = []
            if attachment_key:
                link_parts.append(f"zotero://open-pdf/library/items/{attachment_key}")
                if self.page_index is not None:
                    link_parts.append(f"?page={self.page_index}&annotation={self.key}")
                elif self.page_label:
                    # Fallback to page label if no page index
                    link_parts.append(f"?annotation={self.key}")
                link = "".join(link_parts)
            else:
                # Fallback link without attachment
                link = f"zotero://select/library/items/{self.parent_key}"

            page_text = f"Page {self.page_label}" if self.page_label else "Page ?"

            lines.append(
                f'- <mark class="hltr-{self.color_category}">"{escaped_text}"</mark> '
                f"[{page_text}]({link})"
            )

        # Comment line (indented)
        if self.comment:
            lines.append(f"  - {self.comment}")

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

        # Sort by page index first
        if self.page_index is not None and other.page_index is not None:
            if self.page_index != other.page_index:
                return self.page_index < other.page_index

        # Then by sort index
        if self.sort_index and other.sort_index:
            if self.sort_index != other.sort_index:
                return self.sort_index < other.sort_index

        # Finally by date added
        if self.date_added and other.date_added:
            return self.date_added < other.date_added

        return False
