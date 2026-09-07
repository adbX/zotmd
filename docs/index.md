# ZotMD

ZotMD synchronizes a personal Zotero library and PDF annotations to Obsidian-native Markdown. It also exposes an immutable local API for discovering tagged papers and already-local PDFs through Zotero Desktop.

## What It Does

- Generates canonical YAML frontmatter and one Markdown note per Better BibTeX citation key.
- Detects top-level metadata changes and child-only attachment or annotation changes.
- Keeps each annotation linked to its own Zotero attachment.
- Preserves the user-owned Notes region during updates and citation-key renames.
- Preflights filename collisions and withholds checkpoints after actionable failures.
- Offers a dry run that performs no local mutation.
- Returns complete, typed paper snapshots without loading synchronization configuration or state.

ZotMD supports personal libraries only. Synchronization requires internet access and a read-only Web API key, but Zotero Desktop does not need to be running. [Paper discovery](paper_source_api.md) instead requires Zotero 10 and local API access, but needs no credential or internet connection. macOS is the supported primary platform; other platforms are best effort.

[Get started](getting_started.md){ .md-button .md-button--primary }

## Data Boundary

Synchronization metadata and annotations travel through Zotero's service. Paper discovery makes unauthenticated read requests only to Zotero Desktop on loopback, and the ZotMD process reads PDF bytes only when `fingerprint()` is called. Zotero Desktop may hash local attachments while producing API metadata. ZotMD does not call Zotero write APIs, contact WebDAV, download unavailable files, or copy attachments into the output. Generated notes and SQLite sync state remain on the local machine.
