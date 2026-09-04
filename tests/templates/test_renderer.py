"""Exact-byte and semantic tests for the 0.4 renderer contract."""

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from jinja2 import UndefinedError

from zotmd.models.annotation import Annotation
from zotmd.models.item import ZoteroItem
from zotmd.templates.renderer import RENDER_CONTRACT_VERSION, TemplateRenderer

FIXTURES = Path(__file__).parents[1] / "fixtures" / "rendered"


def _creator(first: str, last: str, creator_type: str = "author") -> dict[str, str]:
    return {
        "creatorType": creator_type,
        "firstName": first,
        "lastName": last,
    }


def _item(**overrides: object) -> ZoteroItem:
    values: dict[str, object] = {
        "key": "ITEM1",
        "version": 1,
        "item_type": "journalArticle",
        "citation_key": "lovelace2024deterministic",
        "title": "Representative Study",
    }
    values.update(overrides)
    return ZoteroItem(**values)  # type: ignore[arg-type]


def _annotation(
    key: str,
    *,
    parent_key: str = "PDF1",
    annotation_type: str = "highlight",
    page_index: int | None = 0,
    page_label: str | None = "1",
    sort_index: str | None = "0001",
    date_added: datetime | None = None,
    text: str | None = None,
    comment: str | None = None,
    color_category: str = "yellow",
) -> Annotation:
    return Annotation(
        key=key,
        parent_key=parent_key,
        version=1,
        annotation_type=annotation_type,
        text=text,
        comment=comment,
        color_category=color_category,
        page_label=page_label,
        page_index=page_index,
        sort_index=sort_index,
        date_added=date_added,
    )


def _representative_case() -> tuple[ZoteroItem, list[Annotation], str]:
    item = _item(
        creators=[
            _creator("Ada", "Lovelace"),
            _creator("Grace", "Hopper"),
            _creator("Alan", "Turing"),
            _creator("Katherine", "Johnson"),
            _creator("Edsger", "Dijkstra"),
            _creator("Barbara", "Liskov"),
            _creator("Excluded", "Editor", "editor"),
        ],
        date="Spring 2024",
        date_added=datetime(2026, 1, 2, 3, 4, 5),
        date_modified=datetime(2026, 2, 3, 4, 5, 6),
        abstract='A <safe> abstract.\nSecond & "final" line.',
        tags=["évidence", "⭐⭐⭐⭐⭐", "/writing", "topic: yaml", "/reading"],
        doi="10.1000/stable",
        url="https://example.test/study?lang=en&view=full",
        publication_title="Journal of Determinism",
        volume="42",
        issue="7",
        pages="10-20",
    )
    annotations = [
        _annotation(
            "LATE",
            parent_key="PDF-B",
            page_index=4,
            page_label="5",
            sort_index="0004",
            text='Later <evidence>\ncontinued & "quoted"',
            comment="Interpret <this>\ncarefully",
            color_category="purple",
        ),
        _annotation(
            "COMMENT",
            parent_key="PDF-A",
            page_index=2,
            page_label="iii",
            sort_index="0002",
            comment="Standalone & useful",
        ),
        _annotation(
            "IMAGE",
            parent_key="PDF-B",
            annotation_type="image",
            page_index=3,
            page_label="4",
            sort_index="0003",
            comment="A diagram <worth keeping>",
        ),
        _annotation(
            "EARLY",
            parent_key="PDF-A",
            page_index=1,
            page_label="2",
            sort_index="0001",
            text="Earlier evidence",
            color_category="green",
        ),
    ]
    notes = "Keep **these** user bytes.\n\n- A note"
    return item, annotations, notes


def _unicode_case() -> tuple[ZoteroItem, list[Annotation], str]:
    item = _item(
        key="WEB1",
        item_type="webpage",
        citation_key="müller2025yes",
        title='YAML: "yes" # naïve 日本語',
        creators=[
            _creator("Zoë", "Müller"),
            _creator("José", "Núñez"),
            _creator("李", "雷"),
            _creator("Søren", "Kierkegaard"),
            _creator("Renée", "Faßbinder"),
            _creator("Not", "An Author", "editor"),
        ],
        date="2025-04-03",
        venue="Research: Notes",
        url="https://例え.test/yes#résumé",
    )
    return item, [], ""


def _minimal_case() -> tuple[ZoteroItem, list[Annotation], str]:
    return (
        _item(
            key="PRE1",
            item_type="preprint",
            citation_key="minimal2026preprint",
            title="Minimal Preprint",
        ),
        [],
        "",
    )


GOLDEN_CASES = {
    "representative-article.md": _representative_case,
    "unicode-web-page.md": _unicode_case,
    "minimal-preprint.md": _minimal_case,
}


def _split_document(rendered: str) -> tuple[dict[str, object], str]:
    assert rendered.startswith("---\n")
    frontmatter, body = rendered[4:].split("\n---\n\n", 1)
    metadata = yaml.safe_load(frontmatter)
    assert isinstance(metadata, dict)
    return metadata, body


@pytest.mark.parametrize("fixture_name", GOLDEN_CASES)
def test_builtin_render_matches_golden_bytes_and_safe_yaml(fixture_name: str):
    item, annotations, notes = GOLDEN_CASES[fixture_name]()
    rendered = TemplateRenderer().render_item(item, annotations, "PERSONAL", notes)
    expected = (FIXTURES / fixture_name).read_bytes()

    assert rendered.encode("utf-8") == expected
    metadata, _ = _split_document(rendered)
    assert metadata == yaml.safe_load(expected.decode("utf-8").split("---", 2)[1])
    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")


def test_representative_frontmatter_has_exact_order_and_semantics():
    item, annotations, notes = _representative_case()
    metadata, body = _split_document(
        TemplateRenderer().render_item(item, annotations, "PERSONAL", notes)
    )

    assert list(metadata) == [
        "title",
        "categories",
        "kind",
        "generator",
        "citation-key",
        "zotero-key",
        "zotero-item-type",
        "authors",
        "author-count",
        "year",
        "venue",
        "doi",
        "url",
        "zotero-uri",
        "zotero-tags",
        "zotero-states",
        "rating",
        "aliases",
    ]
    assert metadata["authors"] == [
        "Ada Lovelace",
        "Grace Hopper",
        "Alan Turing",
        "Katherine Johnson",
        "Edsger Dijkstra",
    ]
    assert metadata["author-count"] == 6
    assert metadata["zotero-tags"] == [
        "/reading",
        "/writing",
        "topic: yaml",
        "évidence",
        "⭐⭐⭐⭐⭐",
    ]
    assert metadata["zotero-states"] == ["reading", "writing"]
    assert metadata["rating"] == 5
    assert metadata["aliases"] == ["lovelace2024deterministic"]
    assert [line for line in body.splitlines() if line.startswith("# ")] == [
        "# Representative Study"
    ]
    assert "## Annotations\n\n" in body
    assert (
        not {
            "citekey",
            "itemType",
            "dateAdded",
            "status",
            "category",
            "tags",
            "links",
        }
        & metadata.keys()
    )
    assert "%% begin" not in body
    assert "Related Literature" not in body
    assert "Annotation Color Key" not in body


def test_five_authors_have_no_author_count_and_unicode_is_preserved():
    item, annotations, notes = _unicode_case()
    rendered = TemplateRenderer().render_item(item, annotations, "PERSONAL", notes)
    metadata, _ = _split_document(rendered)

    assert len(metadata["authors"]) == 5
    assert "author-count" not in metadata
    assert 'YAML: "yes" # naïve 日本語' in rendered
    assert "müller2025yes" in rendered


def test_absent_optional_values_are_omitted_and_sections_are_still_present():
    item, annotations, notes = _minimal_case()
    metadata, body = _split_document(
        TemplateRenderer().render_item(item, annotations, "PERSONAL", notes)
    )

    assert list(metadata) == [
        "title",
        "categories",
        "kind",
        "generator",
        "citation-key",
        "zotero-key",
        "zotero-item-type",
        "zotero-uri",
        "aliases",
    ]
    assert body == (
        "# Minimal Preprint\n\n"
        "## Notes\n\n"
        "<!-- zotmd:notes:start -->\n"
        "<!-- zotmd:notes:end -->\n\n"
        "## Annotations\n"
    )


def test_title_is_single_line_html_safe_and_cannot_spoof_notes_markers():
    title = (
        "First line\r\n"
        "<!-- zotmd:notes:start -->\n"
        "spoofed\n"
        "<!-- zotmd:notes:end --> <script>"
    )
    renderer = TemplateRenderer()
    rendered = renderer.render_item(
        _item(title=title),
        [],
        "PERSONAL",
        "Actual user notes",
    )
    metadata, body = _split_document(rendered)

    normalized = (
        "First line <!-- zotmd:notes:start --> spoofed "
        "<!-- zotmd:notes:end --> <script>"
    )
    assert metadata["title"] == normalized
    assert body.splitlines()[0] == (
        "# First line &lt;!-- zotmd:notes:start --&gt; spoofed "
        "&lt;!-- zotmd:notes:end --&gt; &lt;script&gt;"
    )
    assert [line for line in body.splitlines() if line.startswith("# ")] == [
        body.splitlines()[0]
    ]
    assert renderer.extract_notes_section(rendered) == "Actual user notes"


@pytest.mark.parametrize("title", [None, "", " \r\n "])
def test_renderer_rejects_malformed_titles(title: object):
    with pytest.raises(ValueError, match="Publication title must be a nonblank string"):
        TemplateRenderer().render_item(
            _item(title=title),  # type: ignore[arg-type]
            [],
            "PERSONAL",
        )


@pytest.mark.parametrize(
    ("item_type", "kind"),
    [
        ("journalArticle", "article"),
        ("preprint", "preprint"),
        ("conferencePaper", "conference-paper"),
        ("webpage", "web-page"),
        ("computerProgram", "software"),
        ("bookSection", "book-chapter"),
        ("audioRecording", "audio-recording"),
    ],
)
def test_kind_mapping(item_type: str, kind: str):
    metadata, _ = _split_document(
        TemplateRenderer().render_item(_item(item_type=item_type), [], "PERSONAL")
    )
    assert metadata["kind"] == kind


@pytest.mark.parametrize(
    ("tag", "rating"),
    [("⭐", 1), ("⭐⭐⭐⭐⭐", 5), ("⭐⭐⭐⭐⭐⭐", None)],
)
def test_only_one_to_five_star_tags_become_ratings(tag: str, rating: int | None):
    metadata, _ = _split_document(
        TemplateRenderer().render_item(_item(tags=[tag]), [], "PERSONAL")
    )
    assert metadata.get("rating") == rating
    assert metadata["zotero-tags"] == [tag]


def test_abstract_is_collapsed_escaped_and_keeps_every_line_in_callout():
    rendered = TemplateRenderer().render_item(
        _item(abstract="<script>\n\nA & B"), [], "PERSONAL"
    )
    _, body = _split_document(rendered)

    assert "> [!abstract]-\n> &lt;script&gt;\n>\n> A &amp; B\n\n## Notes" in body


def test_annotation_variants_are_safe_and_use_their_own_parent_keys():
    item, annotations, notes = _representative_case()
    _, body = _split_document(
        TemplateRenderer().render_item(
            item,
            annotations,
            "PERSONAL",
            notes,
            attachment_key="WRONG-SHARED-PDF",
        )
    )

    assert (
        '- <mark class="hltr-purple">Later &lt;evidence&gt;<br>continued &amp; '
        "&quot;quoted&quot;</mark> "
        "[Page 5](zotero://open-pdf/library/items/PDF-B?page=4&annotation=LATE)" in body
    )
    assert "  - Interpret &lt;this&gt;<br>carefully" in body
    assert (
        "- Standalone &amp; useful "
        "[Page iii](zotero://open-pdf/library/items/PDF-A?page=2&annotation=COMMENT)"
        in body
    )
    assert (
        "- Image annotation "
        "[Page 4](zotero://open-pdf/library/items/PDF-B?page=3&annotation=IMAGE)"
        in body
    )
    assert "![" not in body
    assert "WRONG-SHARED-PDF" not in body
    assert (
        body.index("EARLY")
        < body.index("COMMENT")
        < body.index("IMAGE")
        < body.index("LATE")
    )


def test_annotation_without_page_index_still_links_to_the_annotation():
    annotation = _annotation(
        "ANN1",
        parent_key="PDF-X",
        page_index=None,
        page_label="Appendix",
        text="Evidence",
    )

    assert TemplateRenderer.render_annotation_markdown(annotation).endswith(
        "[Page Appendix](zotero://open-pdf/library/items/PDF-X?annotation=ANN1)"
    )


def test_annotation_sorting_has_a_total_deterministic_fallback():
    annotations = [
        _annotation("B", page_index=None, sort_index=None),
        _annotation("A", page_index=None, sort_index=None),
        _annotation("PAGE", page_index=2, sort_index=None),
    ]

    assert [annotation.key for annotation in sorted(annotations)] == ["PAGE", "A", "B"]


def test_notes_preserve_only_exact_new_marker_content():
    renderer = TemplateRenderer()
    notes = "first line\n\n%% begin notes %%\nlegacy text\n%% end notes %%\nlast line\n"
    existing = renderer.render_item(_item(), [], "PERSONAL", notes)

    assert renderer.extract_notes_section(existing) == notes
    assert (
        renderer.extract_notes_section(
            "%% begin notes %%\nlegacy text\n%% end notes %%"
        )
        is None
    )


def test_custom_template_controls_only_body_and_gets_new_context(tmp_path: Path):
    template_path = tmp_path / "body.md.j2"
    template_path.write_text(
        "# Custom {{ title }}\n\n"
        "Annotations: {{ annotations | map(attribute='key') | join(',') }}\n\n"
        "{{ preserved_notes }}\n",
        encoding="utf-8",
    )
    item = _item(title='Canonical: "Title"')
    annotations = [
        _annotation("LATE", page_index=8),
        _annotation("EARLY", page_index=2),
    ]

    rendered = TemplateRenderer(template_path).render_item(
        item, annotations, "PERSONAL", "Custom notes", attachment_key="IGNORED"
    )
    metadata, body = _split_document(rendered)

    assert metadata["title"] == 'Canonical: "Title"'
    assert body == (
        '# Custom Canonical: "Title"\n\nAnnotations: EARLY,LATE\n\nCustom notes\n'
    )


def test_custom_template_gets_normalized_safe_title_and_cannot_spoof_notes(
    tmp_path: Path,
):
    template_path = tmp_path / "body.md.j2"
    template_path.write_text(
        "# {{ title }}\n\n"
        "Raw item title: {{ item.title }}\n\n"
        "## Notes\n"
        "<!-- zotmd:notes:start -->\n"
        "{{ preserved_notes }}\n"
        "<!-- zotmd:notes:end -->\n",
        encoding="utf-8",
    )
    malicious_title = (
        "First\n<!-- zotmd:notes:start -->\nspoofed\n<!-- zotmd:notes:end --> <script>"
    )
    renderer = TemplateRenderer(template_path)

    rendered = renderer.render_item(
        _item(title=malicious_title),
        [],
        "PERSONAL",
        "Actual user notes",
    )
    metadata, body = _split_document(rendered)

    normalized = (
        "First <!-- zotmd:notes:start --> spoofed <!-- zotmd:notes:end --> <script>"
    )
    assert metadata["title"] == normalized
    assert body.splitlines()[0].endswith("&lt;script&gt;")
    assert f"Raw item title: {normalized}" in body
    assert renderer.extract_notes_section(rendered) == "Actual user notes"


def test_custom_template_uses_strict_undefined_and_has_no_old_context(tmp_path: Path):
    template_path = tmp_path / "strict.md.j2"
    template_path.write_text("{{ new_annotations }}\n", encoding="utf-8")

    with pytest.raises(UndefinedError):
        TemplateRenderer(template_path).render_item(_item(), [], "PERSONAL")


def test_missing_direct_custom_template_is_an_error(tmp_path: Path):
    missing = tmp_path / "missing.md.j2"

    with pytest.raises(FileNotFoundError, match="Custom body template does not exist"):
        TemplateRenderer(missing)


def test_template_identity_and_render_contract_are_exposed(tmp_path: Path):
    built_in = TemplateRenderer()
    template_path = Path(built_in.template.filename or "")
    assert (
        built_in.get_template_hash()
        == hashlib.sha256(template_path.read_bytes()).hexdigest()
    )
    assert built_in.get_template_path_identifier() == "built-in"
    assert RENDER_CONTRACT_VERSION == 2

    custom_path = tmp_path / "custom.md.j2"
    custom_path.write_text("Custom body\n", encoding="utf-8")
    custom = TemplateRenderer(custom_path)
    assert custom.get_template_hash() == hashlib.sha256(b"Custom body\n").hexdigest()
    assert custom.get_template_path_identifier() == str(custom_path.resolve())

    custom_path.write_text("Changed after renderer construction\n", encoding="utf-8")
    assert custom.get_template_hash() == hashlib.sha256(b"Custom body\n").hexdigest()


def test_custom_template_hash_tracks_only_recursive_static_dependencies(
    tmp_path: Path,
):
    main = tmp_path / "main.md.j2"
    base = tmp_path / "base.md.j2"
    partial = tmp_path / "partial.md.j2"
    macros = tmp_path / "macros.md.j2"
    unrelated = tmp_path / "unrelated.md.j2"
    main.write_text(
        '{% extends "base.md.j2" %}\n'
        '{% import "macros.md.j2" as macros %}\n'
        "{% block body %}{{ macros.label() }}{% endblock %}\n",
        encoding="utf-8",
    )
    base.write_text(
        '{% include "partial.md.j2" %}\n{% block body %}{% endblock %}\n',
        encoding="utf-8",
    )
    partial.write_text("Partial one\n", encoding="utf-8")
    macros.write_text("{% macro label() %}Label one{% endmacro %}\n", encoding="utf-8")
    unrelated.write_text("Unrelated one\n", encoding="utf-8")

    original = TemplateRenderer(main).get_template_hash()
    unrelated.write_text("Unrelated two\n", encoding="utf-8")
    assert TemplateRenderer(main).get_template_hash() == original

    partial.write_text("Partial two\n", encoding="utf-8")
    partial_changed = TemplateRenderer(main).get_template_hash()
    assert partial_changed != original

    base.write_text(
        '{% include "partial.md.j2" %}\nBase two\n{% block body %}{% endblock %}\n',
        encoding="utf-8",
    )
    base_changed = TemplateRenderer(main).get_template_hash()
    assert base_changed != partial_changed

    macros.write_text("{% macro label() %}Label two{% endmacro %}\n", encoding="utf-8")
    assert TemplateRenderer(main).get_template_hash() != base_changed


def test_dynamic_custom_template_dependency_is_rejected(tmp_path: Path):
    template_path = tmp_path / "dynamic.md.j2"
    template_path.write_text("{% include item.template_name %}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="static template names"):
        TemplateRenderer(template_path)
