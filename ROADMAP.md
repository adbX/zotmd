# Roadmap

ZotMD synchronizes one personal Zotero library and its PDF annotations to generated Markdown notes. Version 0.4 establishes a safe one-way synchronization contract that preserves concurrent local changes and makes interrupted writes recoverable.

## Product direction

Version 0.5 is planned to introduce a paper-source API. The API will separate source retrieval from Markdown reconciliation so supported paper sources can expose a consistent, typed record contract without weakening ZotMD's local safety guarantees.

Later work may improve configuration diagnostics, template tooling, and source coverage. New capabilities must preserve deterministic output, read-only remote access, dry-run immutability, and recoverable local mutations.

## Scope

Group libraries, linked-file copying, and bidirectional synchronization remain outside the current product scope. They require separate identity, ownership, and conflict-resolution designs rather than extensions to the personal-library contract.
