# ZotMD

**Sync your Zotero library to Markdown files with automatic updates and PDF annotation extraction.**

ZotMD is a command-line tool that synchronizes your Zotero library to beautifully formatted Markdown files, perfect for use with Obsidian, Logseq, or any other Markdown-based note-taking app.

## Features

- **Smart Sync**: Incremental sync only updates changed items
- **PDF Annotations**: Automatically extracts highlights and notes from PDFs
- **Customizable Templates**: Use Jinja2 templates to format your notes
- **Citation Keys**: Uses Better BibTeX citation keys for consistent filenames
- **User Notes**: Preserves your custom notes across syncs
- **Configurable**: Simple TOML configuration file
- **Cross-Platform**: Works on macOS, Linux, and Windows

## Quick Start

```bash
# Install with uv (recommended)
uv tool install zotmd

# Or with pipx
pipx install zotmd

# Initialize configuration
zotmd init

# Sync your library
zotmd sync
```

## Example Output

Each Zotero item becomes a Markdown file named after its citation key:

```markdown
---
title: "The Structure of Scientific Revolutions"
authors: Thomas S. Kuhn
year: 1962
itemType: book
tags:
  - philosophy-of-science
  - paradigm-shifts
citationKey: kuhn1962structure
---

# The Structure of Scientific Revolutions

## Metadata

- **Authors:** Thomas S. Kuhn
- **Year:** 1962
- **Publisher:** University of Chicago Press
- **ISBN:** 978-0226458083

## Abstract

A landmark in intellectual history...

## Annotations

### Page 10 (Yellow)

> "Normal science means research firmly based upon one or more past scientific achievements..."

My note: This is the definition of normal science according to Kuhn.

## Notes

<!-- Add your custom notes below this line -->
<!-- They will be preserved across syncs -->

```

## Prerequisites

1. **Better BibTeX**: Required for citation keys
   - Install from [retorque.re/zotero-better-bibtex](https://retorque.re/zotero-better-bibtex/)

2. **Zotero API Access**:
   - Enable API access in Zotero Settings → Advanced → Miscellaneous
   - Generate an API key at [zotero.org/settings/keys](https://www.zotero.org/settings/keys)

## Next Steps

- [Installation Guide](installation.md)
- [Getting Started](getting-started.md)
- [Usage & Commands](usage.md)
- [Configuration Reference](configuration.md)
