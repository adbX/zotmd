# ZotMD

Sync one personal Zotero library and its PDF annotations to Obsidian-ready Markdown.

- One note per Better BibTeX citation key
- Incremental metadata, attachment, annotation, rename, and removal updates
- User-written Notes preserved across rerenders
- Read-only Zotero Web API access
- Mutation-free dry runs
- Separate Python API for tagged papers and already-local PDFs

## Limits

- Personal libraries only
- One-way synchronization from Zotero to Markdown
- macOS primary; other platforms best effort
- PDFs linked from generated notes, not copied

## Install

Requirements: Python 3.13 or newer, [uv](https://docs.astral.sh/uv/), [Better BibTeX](https://retorque.re/zotero-better-bibtex/), and a read-only [Zotero API key](https://www.zotero.org/settings/keys/new).

```bash
uv tool install zotmd
zotmd config
zotmd sync --full --dry-run
zotmd sync --full
```

Later updates:

```bash
zotmd sync
```

## Documentation

- [Synchronize notes](https://adbX.github.io/zotmd/getting_started/): setup, preview, and first sync
- [Configure synchronization](https://adbX.github.io/zotmd/configuration/): paths, removals, and templates
- [Discover local papers](https://adbX.github.io/zotmd/paper_discovery/): typed Python records and validated PDF fingerprints
- [Troubleshoot ZotMD](https://adbX.github.io/zotmd/troubleshooting/): common failures and safe recovery

## License

[MIT](LICENSE)
