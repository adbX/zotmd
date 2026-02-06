# ZotMD

**Sync your Zotero library to Markdown files with automatic updates and PDF annotation extraction.**

Built for Obsidian and compatible with any Markdown-based note-taking app.

## Features

- **Library Sync**: Keeps your Zotero library and Obsidian folder of markdown notes in sync. Uses incremental sync by default that only updates changed items that also keeps track of modified highlights and annotations.
- **PDF Annotations**: Extracts highlights and notes created in Zotero
- **Customizable Templates**: Uses Jinja2 to create markdown notes with custom templates

## Quick Start

```bash
# Install with uv (https://docs.astral.sh/uv/)
uv tool install zotmd

# Set up configuration
zotmd init

# Sync your library
zotmd sync
```

## Requirements

- Python 3.13+
- [Better BibTeX](https://retorque.re/zotero-better-bibtex/) (Zotero plugin)
- [Zotero API access](https://www.zotero.org/settings/security)

## [Documentation](https://adbX.github.io/zotmd/)

## License

MIT License - see [LICENSE](LICENSE) for details.