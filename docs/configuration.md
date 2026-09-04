# Configuration

ZotMD uses one closed-schema TOML file. Unknown sections and keys are rejected so misspellings cannot silently change behavior.

## Locations

| Data | macOS default | Linux default |
|---|---|---|
| Configuration | `~/Library/Application Support/zotmd/config.toml` | `~/.config/zotmd/config.toml` |
| State | `~/Library/Application Support/zotmd/sync.sqlite` | `~/.local/share/zotmd/sync.sqlite` |

Platform defaults come from `platformdirs`. Run `zotmd status` to see the effective paths.

## Schema

```toml
[zotero]
library_id = "1234567"
api_key = "read-only-key"

[sync]
output_dir = "~/Documents/references"
deletion_behavior = "move"

[advanced]
db_path = ""
template_path = ""
```

`zotero.library_id` identifies a personal library. Group IDs and a `library_type` key are not supported. `zotero.api_key` may be omitted when `ZOTMD_API_KEY` is set; the environment value always takes precedence.

`sync.output_dir` is the generated-note directory. Changing it for the same library moves all state-managed active and removed notes after collision and permission checks. Unmanaged files are not moved.

`sync.deletion_behavior` is either `move` or `delete`. The recommended `move` value places removed notes under `output_dir/removed/`. The `delete` value permanently deletes them.

`advanced.db_path` and `advanced.template_path` are optional. Empty strings select the platform state path and built-in body template. Relative paths are resolved from the directory containing `config.toml`, not from the current working directory.

The configuration writer atomically replaces the file and sets mode `0600`. API keys are still secrets and must not be committed or included in diagnostic logs.

## Generated Frontmatter

ZotMD owns frontmatter and writes populated fields in this order:

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

`categories` is always `sources`. Zotero item types are converted to kebab-case knowledge-note kinds. Only creators with `creatorType = "author"` are included, with at most five names and an `author-count` when more exist. Manual Zotero tags are retained exactly and sorted; automatic tags are excluded. Slash tags also populate `zotero-states`, and a tag consisting entirely of one to five star characters sets `rating`. ZotMD normalizes title line breaks before rendering and provides an HTML-escaped title for body headings.

## User Notes

The built-in body always contains:

```markdown
## Notes
<!-- zotmd:notes:start -->
<!-- zotmd:notes:end -->

## Annotations
```

Only text inside those exact boundaries is user-owned and preserved. Frontmatter, the title, abstract, section headings, and annotations are regenerated. Old percent-style markers from ZotMD 0.3 are not recognized.

## Custom Body Templates

A custom Jinja2 template controls only the body. ZotMD always prepends canonical frontmatter. Do not copy the built-in template as a custom template because it uses internal section variables that are not part of the custom context.

The complete custom context contains four variables:

- `item`: a `ZoteroItem` with `key`, `version`, `item_type`, `citation_key`, normalized single-line `title`, `creators`, `date`, `date_added`, `date_modified`, `abstract`, `tags`, `doi`, `url`, `pdf_link`, `publication_title`, `volume`, `issue`, `pages`, `publisher`, `venue`, `collections`, `relations`, `extra`, `creator_summary`, and `num_children`.
- `title`: the normalized title with HTML syntax escaped, ready for a Markdown heading.
- `annotations`: a sorted list of `Annotation` objects. Each has `key`, `parent_key`, `version`, `annotation_type`, `text`, `comment`, `color_hex`, `color_category`, `page_label`, `page_index`, `position`, `date_added`, `date_modified`, and `sort_index`.
- `preserved_notes`: the exact text previously found inside the Notes boundaries, or an empty string.

Undefined names are errors. A minimal custom body that keeps Notes preservation is:

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

After changing a custom template, run `zotmd sync --dry-run`. ZotMD detects changes to the selected template and its recursive static `include`, `extends`, and `import` dependencies without hashing unrelated files. Dynamic template names are rejected because their dependencies cannot be tracked deterministically. A detected template or render-contract change plans a rerender of every active note.
