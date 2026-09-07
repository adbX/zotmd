# Roadmap

ZotMD synchronizes one personal Zotero library and its PDF annotations to generated Markdown notes. Version 0.4 established a safe one-way synchronization contract that preserves concurrent local changes and makes interrupted writes recoverable. Version 0.5 adds a separate immutable paper-source API over Zotero 10's local HTTP API.

## Product direction

The 0.5 paper-source API reads one stable personal-library snapshot and validates already-local stored PDFs without using synchronization configuration or state. Source, documentation, mocked validation, artifact checks, the read-only local smoke test, review, and protected merge are complete. The existing note synchronizer remains on the Web API, and 0.5 publication must follow the preserved 0.4 release.

Later work may connect Zotero-native notes and ZotMD-generated Markdown notes to paper catalogs. It may also improve configuration diagnostics, template tooling, and source coverage. New capabilities must preserve deterministic output, read-only remote access, dry-run immutability, and recoverable local mutations.

## Scope

Group libraries, linked-file copying, and bidirectional synchronization remain outside the current product scope. They require separate identity, ownership, and conflict-resolution designs rather than extensions to the personal-library contract.
