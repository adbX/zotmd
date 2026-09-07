# Getting Started

## 1. Prepare Zotero

Install [Better BibTeX](https://retorque.re/zotero-better-bibtex/) and ensure each item to be exported has a citation key. ZotMD skips items without one and reports their Zotero keys.

At [Zotero settings](https://www.zotero.org/settings/keys), find the numeric user ID for your personal library. Create a dedicated private key with personal-library read access, no write access, and no group access.

ZotMD uses the Zotero Web API. Zotero Desktop does not need to be running, and the local API setting does not affect synchronization.

## 2. Install ZotMD

Install Python 3.13 or newer and ZotMD with [uv](https://docs.astral.sh/uv/):

```bash
uv python install 3.13
uv tool install zotmd
```

## 3. Configure ZotMD

Run the interactive setup:

```bash
zotmd config
```

Enter the personal-library user ID, API key, Obsidian references directory, deletion behavior, and optional state or custom-template paths. API-key input is hidden.

To avoid storing the API key, export it before setup and every later ZotMD command:

```bash
export ZOTMD_API_KEY="your-read-only-key"
zotmd config
```

Setup uses the environment key for its connection test without writing it to `config.toml`.

## 4. Preview and Sync

Preview a fresh full synchronization:

```bash
zotmd sync --full --dry-run
```

Review the planned creates, rewrites, renames, removals, permanent deletions, output moves, missing citation keys, collisions, and errors. A dry run does not create an output directory or database when either is absent.

When the preview is clean, back up any existing output and run:

```bash
zotmd sync --full
```

Use `zotmd sync` for later incremental updates.

## Upgrading From 0.3

ZotMD 0.4 intentionally does not migrate 0.3 state, old Notes markers, or the old `zotero.library_type` configuration key. Keep the existing output as a backup, archive the old `sync.sqlite`, then run `zotmd config` to rewrite the configuration for a personal library and choose a new empty output directory. Run a fresh 0.4 full sync and keep the backups until the new corpus and a second no-op incremental sync have been checked.

Continue with [Configuration](configuration.md) and [Usage](usage.md).

## Using the Paper-Source API

The paper-source API is part of the unreleased 0.5 source and is not included in the latest PyPI package yet. `uv tool install zotmd` will provide it only after 0.5 is published.

Paper discovery is independent of the setup above. It does not read `config.toml`, `sync.sqlite`, generated notes, or the Web API key. Start Zotero 10, enable local API access in its advanced settings, ensure the selected top-level papers have one exact manual tag, and call `iter_papers(tag="paper-source")` from Python.

Zotero remains responsible for WebDAV. Open or download a PDF through Zotero before discovery if it is not already local; ZotMD reports an unavailable file but does not fetch it. See the [local paper-source API](paper_source_api.md) for imports, diagnostics, and fingerprinting.
