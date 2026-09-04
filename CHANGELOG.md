# Changelog

This changelog records user-visible changes to ZotMD.

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
