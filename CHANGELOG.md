# Changelog

This changelog records user-visible changes to ZotMD.

## 0.5.1 - 2026-09-16

### Changed

- Corrected the package description to state that the paper-source API is included in the PyPI package.
- Reorganized public documentation into separate synchronization and paper-discovery paths, with a concise README, side-by-side landing cards, and focused reference pages so readers can choose a workflow before opening details. Light mode is now the site default.

## 0.5.0 - 2026-09-16

### Added

- Added `iter_papers()` and immutable paper, identifier, diagnostic, PDF attachment, and fingerprint records for Zotero 10's local HTTP API.
- Added stable version-bracketed snapshots, exact manual-tag selection, DOI and arXiv normalization, complete PDF-candidate classification, and lazy one-pass SHA-256 and MD5 fingerprinting.
- Added no-follow local path validation for already-local stored attachments and diagnostics for unavailable, linked, unsupported, ambiguous, malformed, empty, unreadable, and symlinked PDF candidates.

### Changed

- Native Zotero `citationKey` metadata now takes precedence over the structured Better BibTeX `Citation Key:` line in `Extra`.
- Pyzotero is constrained to `>=1.15.1,<2` and httpx2 to `>=2.12.0,<3` for the characterized Zotero 10 local API behavior. The loopback client ignores environment proxies and rejects redirects.
- Existing `zotmd sync` behavior remains on the authenticated Zotero Web API and schema-4 state; paper discovery loads neither synchronization configuration nor state.

## 0.4.0 - 2026-09-03

### Added

- Added dry-run planning that reads Zotero, templates, state, and managed notes without changing local files or checkpoints.
- Added stable remote snapshots, durable file-change receipts, two-phase checkpoints, target-collision reporting, and guarded rollback for interrupted or concurrent changes.
- Added canonical YAML frontmatter, recursive static template dependency tracking, explicit move or delete behavior for removed Zotero items, and support for Python 3.13 and 3.14.

### Changed

- Synchronization is limited to one personal Zotero user library and uses only Zotero read APIs.
- Trashed and deleted records now follow explicit removal behavior, while an active item that loses its citation key remains managed and unchanged.
- User text is preserved only inside the `<!-- zotmd:notes:start -->` and `<!-- zotmd:notes:end -->` markers.

### Breaking changes

- ZotMD 0.4 requires fresh schema-version-4 state. It does not migrate a 0.3 database.
- The old `zotero.library_type` setting is rejected. Run `zotmd config` to create the current personal-library configuration.
- Old percent-style and generic Notes markers are not recognized.
- Before upgrading, retain the existing output and state as backups, select a distinct empty output directory, and run a fresh full synchronization.
