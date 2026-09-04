# ZotMD

ZotMD synchronizes a personal Zotero library and PDF annotations to Obsidian-native Markdown. It uses authenticated, read-only Zotero Web API requests and preserves user text inside explicit Notes boundaries.

## What It Does

- Generates canonical YAML frontmatter and one Markdown note per Better BibTeX citation key.
- Detects top-level metadata changes and child-only attachment or annotation changes.
- Keeps each annotation linked to its own Zotero attachment.
- Preserves the user-owned Notes region during updates and citation-key renames.
- Preflights filename collisions and withholds checkpoints after actionable failures.
- Offers a dry run that performs no local mutation.

ZotMD supports personal libraries only. Synchronization requires internet access, but Zotero Desktop does not need to be running. macOS is the supported primary platform; other platforms are best effort.

[Get started](getting_started.md){ .md-button .md-button--primary }

## Data Boundary

Bibliographic metadata and annotations travel through Zotero's service. ZotMD does not upload local PDF bytes, call Zotero write APIs, or copy attachments into the output. Generated notes and SQLite sync state remain on the local machine.
