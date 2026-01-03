"""Jinja2 template renderer for markdown files."""

import re
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from ..models.item import ZoteroItem
from ..models.annotation import Annotation


def _format_authors_list(creators: List[dict], limit: int = 5) -> List[str]:
    """
    Format creator list as a list of author name strings.

    Args:
        creators: List of creator dicts from Zotero API
        limit: Maximum number of authors to include (default 5)

    Returns:
        List of formatted author names
    """
    if not creators:
        return []

    names = []
    for creator in creators:
        if "firstName" in creator and "lastName" in creator:
            names.append(f"{creator['firstName']} {creator['lastName']}")
        elif "lastName" in creator:
            names.append(creator["lastName"])
        elif "name" in creator:
            names.append(creator["name"])

    return names[:limit]


def _extract_year(date_string: Optional[str]) -> Optional[int]:
    """
    Extract year from a date string.

    Args:
        date_string: Date string in various formats (e.g., "2025-01-15", "2025")

    Returns:
        Year as integer or None if not found
    """
    if not date_string:
        return None

    match = re.search(r"\b(19|20)\d{2}\b", date_string)
    return int(match.group(0)) if match else None


def _format_date_simple(dt: Optional[datetime]) -> Optional[str]:
    """
    Format datetime as YYYY-MM-DD string.

    Args:
        dt: datetime object

    Returns:
        Formatted date string or None
    """
    if not dt:
        return None
    return dt.strftime("%Y-%m-%d")


class TemplateRenderer:
    """Renders markdown files using Jinja2 templates."""

    # Pattern to extract notes section
    NOTES_PATTERN = re.compile(r"%% begin notes %%\n(.*?)\n%% end notes %%", re.DOTALL)

    # Pattern to extract annotations section
    ANNOTATIONS_PATTERN = re.compile(
        r"%% begin annotations %%\n(.*?)\n%% end annotations %%", re.DOTALL
    )

    def __init__(self, template_path: Optional[Path] = None):
        """
        Initialize Jinja2 environment.

        Args:
            template_path: Path to custom template file. If None, uses default template.
        """
        # Store template path for later reference
        self.template_path_used = template_path

        if template_path and template_path.exists():
            # Load custom template from file
            template_dir = template_path.parent
            self.env = Environment(loader=FileSystemLoader(template_dir))
        else:
            # Use default template (loaded from same directory)
            template_dir = Path(__file__).parent
            self.env = Environment(loader=FileSystemLoader(template_dir))

        # Add custom filters BEFORE loading template
        self.env.filters["format_creators"] = self._format_creators
        self.env.filters["escape_quotes"] = self._escape_quotes
        self.env.filters["clean_title"] = self._clean_title
        self.env.filters["sanitize_tag"] = self._sanitize_tag
        self.env.filters["format_authors_list"] = _format_authors_list
        self.env.filters["extract_year"] = _extract_year
        self.env.filters["format_date_simple"] = _format_date_simple

        # Now load the template (which will compile and validate filters)
        if template_path and template_path.exists():
            self.template = self.env.get_template(template_path.name)
        else:
            self.template = self.env.get_template("default.md.j2")

    @staticmethod
    def _format_creators(creators: List[dict]) -> str:
        """
        Format creator list as comma-separated string.

        Args:
            creators: List of creator dicts

        Returns:
            Formatted string
        """
        if not creators:
            return "Unknown Author"

        names = []
        for creator in creators:
            if "firstName" in creator and "lastName" in creator:
                names.append(f"{creator['firstName']} {creator['lastName']}")
            elif "lastName" in creator:
                names.append(creator["lastName"])
            elif "name" in creator:
                names.append(creator["name"])

        return ", ".join(names) if names else "Unknown Author"

    @staticmethod
    def _escape_quotes(text: str) -> str:
        """Escape double quotes for markdown."""
        if not text:
            return ""
        return text.replace('"', '\\"')

    @staticmethod
    def _clean_title(title: str) -> str:
        """
        Remove problematic characters from title for use in frontmatter.

        Args:
            title: Original title

        Returns:
            Cleaned title suitable for double-quoted YAML strings
        """
        if not title:
            return ""

        cleaned = title
        # Remove characters that cause issues in YAML frontmatter
        # Note: We use double-quoted strings in the template, so single quotes are fine
        for char in [":", "#", "^", "|", "[", "]", "\\", "/", '"']:
            cleaned = cleaned.replace(char, "")

        return cleaned

    @staticmethod
    def _sanitize_tag(tag: str) -> str:
        """
        Sanitize a tag for Obsidian compatibility.

        Preserves slashes for nested tags while handling spaces properly:
        - Removes spaces around slashes: "tools / docker" -> "tools/docker"
        - Replaces remaining spaces with underscores: "machine learning" -> "machine_learning"

        Args:
            tag: Original tag from Zotero

        Returns:
            Sanitized tag suitable for Obsidian nested tags
        """
        if not tag:
            return ""

        # Remove spaces around slashes to preserve nested tag structure
        sanitized = re.sub(r"\s*/\s*", "/", tag)

        # Replace remaining spaces with underscores
        sanitized = sanitized.replace(" ", "_")

        return sanitized

    def extract_notes_section(self, markdown_content: str) -> Optional[str]:
        """
        Extract user notes from existing markdown.

        Args:
            markdown_content: Existing markdown file content

        Returns:
            Notes content or None if not found
        """
        match = self.NOTES_PATTERN.search(markdown_content)
        if match:
            return match.group(1)
        return None

    def extract_annotations_section(self, markdown_content: str) -> Optional[str]:
        """
        Extract annotations from existing markdown.

        Args:
            markdown_content: Existing markdown file content

        Returns:
            Annotations content or None if not found
        """
        match = self.ANNOTATIONS_PATTERN.search(markdown_content)
        if match:
            return match.group(1)
        return None

    def render_item(
        self,
        item: ZoteroItem,
        annotations: List[Annotation],
        library_id: str,
        preserved_notes: Optional[str] = None,
        attachment_key: Optional[str] = None,
    ) -> str:
        """
        Render markdown for a Zotero item.

        Args:
            item: ZoteroItem to render
            annotations: List of annotations for this item
            library_id: Zotero library ID
            preserved_notes: User notes to preserve (from existing file)
            attachment_key: PDF attachment key for annotation links

        Returns:
            Rendered markdown string
        """
        # Sort annotations by page and position
        sorted_annotations = sorted(annotations)

        # Prepare template context
        context = {
            "item": item,
            "annotations": sorted_annotations,
            "new_annotations": sorted_annotations,  # For compatibility with template
            "library_id": library_id,
            "now": datetime.now(),
            "preserved_notes": preserved_notes or "-----------------------",
            "attachment_key": attachment_key,
            # Additional convenience variables
            "clean_title": self._clean_title(item.title),
            "formatted_creators": item.format_creators(),
            "authors_list": _format_authors_list(item.creators, limit=5),
            "year": _extract_year(item.date),
            "date_added_simple": _format_date_simple(item.date_added),
        }

        # Render template
        rendered = self.template.render(**context)

        return rendered

    def render_annotation_markdown(
        self, annotation: Annotation, attachment_key: Optional[str] = None
    ) -> str:
        """
        Render a single annotation to markdown.

        Args:
            annotation: Annotation to render
            attachment_key: PDF attachment key for links

        Returns:
            Markdown formatted annotation
        """
        return annotation.to_markdown(attachment_key)

    def get_template_hash(self) -> str:
        """
        Get SHA256 hash of the current template.

        Returns:
            SHA256 hash of template source content
        """
        # Import here to avoid circular dependency
        import sys
        import os

        # For built-in templates, we need to read the actual file
        # because template.source may not be available in all Jinja2 versions
        if self.template_path_used and self.template_path_used.exists():
            # Custom template - read from file
            template_content = self.template_path_used.read_text(encoding="utf-8")
        else:
            # Built-in template - read from templates directory
            template_file = Path(__file__).parent / "default.md.j2"
            template_content = template_file.read_text(encoding="utf-8")

        # Import TemplateChangeDetector and compute hash
        from ..core.template_manager import TemplateChangeDetector

        return TemplateChangeDetector.compute_template_hash(template_content)

    def get_template_path_identifier(self) -> str:
        """
        Get identifier for the current template.

        Returns:
            "built-in" or absolute path to custom template
        """
        from ..core.template_manager import TemplateChangeDetector

        return TemplateChangeDetector.get_template_identifier(self.template_path_used)
