# Generated notes

ZotMD owns the frontmatter and generated body. You own only the text inside the Notes markers.

## Files and links

- One Markdown note per Better BibTeX citation key
- Canonical YAML frontmatter
- One Zotero link per annotation
- Attachment and PDF links, not copied files

## Frontmatter

Populated fields follow this order:

```yaml
---
title: Exact publication title
categories:
  - sources
kind: article
generator: zotmd
citation-key: example2026
zotero-key: ABCD1234
zotero-item-type: journalArticle
authors:
  - First Author
year: 2026
venue: Example Journal
doi: 10.0000/example
url: https://example.test/paper
zotero-uri: zotero://select/library/items/ABCD1234
zotero-tags:
  - /reading
zotero-states:
  - reading
rating: 5
aliases:
  - example2026
---
```

Field rules:

- `categories`: always `sources`
- `kind`: Zotero item type in kebab-case
- `authors`: authors only, limited to five names
- `author-count`: added when more than five authors exist
- `zotero-tags`: sorted manual tags; automatic tags excluded
- `zotero-states`: slash-prefixed manual tags without the slash
- `rating`: a manual tag containing one to five stars
- `aliases`: Better BibTeX citation key
- `title`: normalized to one line before rendering

Empty optional fields are omitted.

## Notes area

The built-in body includes exact ownership markers:

```markdown
## Notes
<!-- zotmd:notes:start -->
Your notes remain here.
<!-- zotmd:notes:end -->

## Annotations
```

Only text inside the markers survives later synchronization and citation-key renames. Frontmatter, headings, abstracts, and annotations are regenerated.

## Custom body templates

A custom Jinja2 template controls the body only. ZotMD always prepends canonical frontmatter.

| Variable | Value |
|---|---|
| `item` | Current `ZoteroItem` |
| `title` | Single-line title with HTML syntax escaped |
| `annotations` | Sorted `Annotation` objects |
| `preserved_notes` | Exact text from the Notes area, or an empty string |

??? info "`item` fields"

    `key`, `version`, `item_type`, `citation_key`, `title`, `creators`, `date`, `date_added`, `date_modified`, `abstract`, `tags`, `doi`, `url`, `pdf_link`, `publication_title`, `volume`, `issue`, `pages`, `publisher`, `venue`, `collections`, `relations`, `extra`, `creator_summary`, and `num_children`

??? info "Annotation fields"

    `key`, `parent_key`, `version`, `annotation_type`, `text`, `comment`, `color_hex`, `color_category`, `page_label`, `page_index`, `position`, `date_added`, `date_modified`, and `sort_index`

Minimal template with Notes preservation:

```jinja2
# {{ title }}

## Notes
<!-- zotmd:notes:start -->
{{ preserved_notes }}
<!-- zotmd:notes:end -->

## Annotations
{% for annotation in annotations %}
{{ annotation.to_markdown() }}
{% endfor %}
```

Template rules:

- Undefined names: error
- Dynamic template names: rejected
- Tracked dependencies: selected template plus static `include`, `extends`, and `import` files
- Template or render change: rerender every active note

Preview every template change:

```bash
zotmd sync --dry-run
```
