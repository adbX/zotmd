# ZotMD

**Sync your Zotero library to Markdown files with automatic updates and PDF annotation extraction.**

Perfect for use with Obsidian, Logseq, or any Markdown-based note-taking app.

## Features

- 📚 **Smart Sync**: Incremental sync only updates changed items
- 📝 **PDF Annotations**: Automatically extracts highlights and notes
- 🎨 **Customizable Templates**: Use Jinja2 templates to format your notes
- 🔑 **Citation Keys**: Uses Better BibTeX for consistent filenames
- 💾 **User Notes**: Preserves your custom notes across syncs
- ⚙️ **Configurable**: Simple TOML configuration

## Quick Start

```bash
# Install with uv (recommended)
uv tool install zotmd

# Or with pipx
pipx install zotmd

# Set up configuration
zotmd init

# Sync your library
zotmd sync
```

## Requirements

- Python 3.13+
- [Better BibTeX](https://retorque.re/zotero-better-bibtex/) (Zotero plugin)
- Zotero API access (free)

## Documentation

📖 **[Full Documentation](https://adhithyabhaskar.github.io/zotmd/)**

- [Installation Guide](https://adhithyabhaskar.github.io/zotmd/installation/)
- [Getting Started](https://adhithyabhaskar.github.io/zotmd/getting-started/)
- [Usage & Commands](https://adhithyabhaskar.github.io/zotmd/usage/)
- [Configuration](https://adhithyabhaskar.github.io/zotmd/configuration/)
- [Troubleshooting](https://adhithyabhaskar.github.io/zotmd/troubleshooting/)

## Example Output

```markdown
---
title: "The Structure of Scientific Revolutions"
authors: Thomas S. Kuhn
year: 1962
citationKey: kuhn1962structure
tags:
  - philosophy-of-science
  - paradigm-shifts
---

# The Structure of Scientific Revolutions

## Metadata

- **Authors:** Thomas S. Kuhn
- **Year:** 1962
- **Publisher:** University of Chicago Press

## Abstract

A landmark in intellectual history...

## Annotations

### Page 10 (Yellow)

> "Normal science means research firmly based upon one or more past scientific achievements..."

My note: This is the definition of normal science.

## Notes

<!-- Your custom notes are preserved here -->
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please see the [documentation](https://adhithyabhaskar.github.io/zotmd/) for development setup.

## Support

- 📝 [Report Issues](https://github.com/adhithyabhaskar/zotmd/issues)
- 💬 [Discussions](https://github.com/adhithyabhaskar/zotmd/discussions)
- 📖 [Documentation](https://adhithyabhaskar.github.io/zotmd/)
