"""Render Zotero items as canonical Markdown knowledge notes."""

import hashlib
import html
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateNotFound,
    meta,
)

from ..models.annotation import Annotation
from ..models.item import ZoteroItem, normalize_title

RENDER_CONTRACT_VERSION = 2

_KIND_BY_ITEM_TYPE = {
    "journalArticle": "article",
    "preprint": "preprint",
    "conferencePaper": "conference-paper",
    "webpage": "web-page",
    "computerProgram": "software",
    "bookSection": "book-chapter",
}
_YEAR_PATTERN = re.compile(r"(?<!\d)[12]\d{3}(?!\d)")
_RATING_PATTERN = re.compile(r"⭐{1,5}")


class _IndentedSafeDumper(yaml.SafeDumper):
    """Indent block sequence items beneath their mapping key."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def _creator_name(creator: dict[str, Any]) -> str | None:
    first_name = creator.get("firstName")
    last_name = creator.get("lastName")
    if first_name and last_name:
        return f"{first_name} {last_name}"
    if last_name:
        return str(last_name)
    name = creator.get("name")
    return str(name) if name else None


def _kind(item_type: str) -> str:
    if item_type in _KIND_BY_ITEM_TYPE:
        return _KIND_BY_ITEM_TYPE[item_type]
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", item_type)
    return words.lower()


def _year(date: str | None) -> int | None:
    match = _YEAR_PATTERN.search(date) if date else None
    return int(match.group()) if match else None


def _abstract_callout(abstract: str) -> str:
    escaped = html.escape(abstract, quote=True)
    lines = re.split(r"\r\n?|\n", escaped)
    return "> [!abstract]-\n" + "\n".join(
        f"> {line}" if line else ">" for line in lines
    )


class TemplateRenderer:
    """Render canonical frontmatter and a built-in or custom body template."""

    NOTES_PATTERN = re.compile(
        r"^<!-- zotmd:notes:start -->\r?\n(.*?)(?:\r?\n)?"
        r"^<!-- zotmd:notes:end -->\r?$",
        re.MULTILINE | re.DOTALL,
    )
    ANNOTATIONS_PATTERN = re.compile(
        r"^## Annotations[ \t]*\r?\n(?:\r?\n)?(.*)\Z",
        re.MULTILINE | re.DOTALL,
    )

    def __init__(self, template_path: Path | None = None) -> None:
        self.template_path_used = template_path
        self._custom_template = template_path is not None

        if template_path is not None:
            if not template_path.is_file():
                raise FileNotFoundError(
                    f"Custom body template does not exist: {template_path}"
                )
            template_dir = template_path.parent
            template_name = template_path.name
        else:
            template_dir = Path(__file__).parent
            template_name = "default.md.j2"

        loader = FileSystemLoader(template_dir)
        self.env = Environment(
            loader=loader,
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        source, filename, _ = loader.get_source(self.env, template_name)
        self.template = self.env.from_string(source)
        self.template.name = template_name
        self.template.filename = filename
        self._template_hash = self._dependency_hash(loader, template_name, source)

    def _dependency_hash(
        self,
        loader: FileSystemLoader,
        template_name: str,
        root_source: str,
    ) -> str:
        """Hash the selected template and only its static recursive dependencies."""
        sources: dict[str, str | None] = {}

        def collect(name: str, source: str | None = None) -> None:
            if name in sources:
                return
            if source is None:
                try:
                    source, _, _ = loader.get_source(self.env, name)
                except TemplateNotFound:
                    sources[name] = None
                    return
            sources[name] = source
            references = list(meta.find_referenced_templates(self.env.parse(source)))
            if any(reference is None for reference in references):
                raise ValueError(
                    "Custom template dependencies must use static template names"
                )
            dependencies = {
                reference for reference in references if reference is not None
            }
            for dependency in sorted(dependencies):
                collect(dependency)

        collect(template_name, root_source)
        digest = hashlib.sha256(root_source.encode("utf-8"))
        for name in sorted(sources.keys() - {template_name}):
            source = sources[name]
            encoded_name = name.encode("utf-8")
            encoded_source = source.encode("utf-8") if source is not None else b""
            digest.update(b"\0zotmd-template-dependency\0")
            digest.update(len(encoded_name).to_bytes(8, "big"))
            digest.update(encoded_name)
            digest.update(b"\1" if source is not None else b"\0")
            digest.update(len(encoded_source).to_bytes(8, "big"))
            digest.update(encoded_source)
        return digest.hexdigest()

    @staticmethod
    def _metadata(item: ZoteroItem) -> dict[str, object]:
        metadata: dict[str, object] = {
            "title": normalize_title(item.title),
            "categories": ["sources"],
            "kind": _kind(item.item_type),
            "generator": "zotmd",
            "citation-key": item.citation_key,
            "zotero-key": item.key,
            "zotero-item-type": item.item_type,
        }

        author_creators = [
            creator
            for creator in item.creators
            if creator.get("creatorType") == "author"
        ]
        authors = [
            name
            for creator in author_creators[:5]
            if (name := _creator_name(creator)) is not None
        ]
        if authors:
            metadata["authors"] = authors
        if len(author_creators) > 5:
            metadata["author-count"] = len(author_creators)

        if (year := _year(item.date)) is not None:
            metadata["year"] = year
        if venue := item.venue or item.publication_title or item.publisher:
            metadata["venue"] = venue
        if item.doi:
            metadata["doi"] = item.doi
        if item.url:
            metadata["url"] = item.url
        if item.key:
            metadata["zotero-uri"] = f"zotero://select/library/items/{item.key}"

        zotero_tags = sorted(item.tags)
        if zotero_tags:
            metadata["zotero-tags"] = zotero_tags
        states = sorted(
            tag[1:] for tag in zotero_tags if tag.startswith("/") and tag[1:]
        )
        if states:
            metadata["zotero-states"] = states
        ratings = [len(tag) for tag in zotero_tags if _RATING_PATTERN.fullmatch(tag)]
        if ratings:
            metadata["rating"] = max(ratings)
        if item.citation_key:
            metadata["aliases"] = [item.citation_key]
        return metadata

    @classmethod
    def _frontmatter(cls, item: ZoteroItem) -> str:
        serialized = yaml.dump(
            cls._metadata(item),
            Dumper=_IndentedSafeDumper,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        return f"---\n{serialized}---"

    def extract_notes_section(self, markdown_content: str) -> str | None:
        """Return exactly the user content inside the 0.4 Notes boundaries."""
        match = self.NOTES_PATTERN.search(markdown_content)
        return match.group(1) if match else None

    def extract_annotations_section(self, markdown_content: str) -> str | None:
        """Return the generated Annotations section for current sync bookkeeping."""
        match = self.ANNOTATIONS_PATTERN.search(markdown_content)
        return match.group(1) if match else None

    def render_item(
        self,
        item: ZoteroItem,
        annotations: list[Annotation],
        library_id: str,
        preserved_notes: str | None = None,
        attachment_key: str | None = None,
    ) -> str:
        """Render one note; attachment links come from each annotation's parent."""
        del library_id, attachment_key
        normalized_title = normalize_title(item.title)
        if normalized_title != item.title:
            item = replace(item, title=normalized_title)
        notes = preserved_notes if preserved_notes is not None else ""
        sorted_annotations = sorted(annotations)
        context: dict[str, object] = {
            "item": item,
            "title": html.escape(normalized_title, quote=False),
            "annotations": sorted_annotations,
            "preserved_notes": notes,
        }
        if not self._custom_template:
            rendered_annotations = [
                rendered
                for annotation in sorted_annotations
                if (rendered := annotation.to_markdown())
            ]
            context.update(
                abstract_section=(
                    f"{_abstract_callout(item.abstract)}\n\n" if item.abstract else ""
                ),
                notes_section=f"{notes}\n" if notes else "",
                annotations_section=(
                    "\n\n" + "\n".join(rendered_annotations)
                    if rendered_annotations
                    else ""
                ),
            )

        body = self.template.render(**context).lstrip("\r\n").rstrip("\r\n")
        return f"{self._frontmatter(item)}\n\n{body}\n"

    @staticmethod
    def render_annotation_markdown(annotation: Annotation) -> str:
        """Render one annotation using its own parent attachment key."""
        return annotation.to_markdown()

    def get_template_hash(self) -> str:
        """Return the SHA-256 hash of the compiled body template."""
        return self._template_hash

    def get_template_path_identifier(self) -> str:
        """Return ``built-in`` or the custom body's absolute path."""
        return (
            str(self.template_path_used.resolve())
            if self.template_path_used is not None
            else "built-in"
        )
