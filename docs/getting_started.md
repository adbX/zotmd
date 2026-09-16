# Synchronize notes

Create Markdown notes from one personal Zotero library.

## Before you start

- macOS, or another platform on a best-effort basis
- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)
- Personal Zotero library
- [Better BibTeX](https://retorque.re/zotero-better-bibtex/) citation keys
- Numeric Zotero user ID
- Dedicated [Zotero API key](https://www.zotero.org/settings/keys/new): personal-library read access, no write or group access
- Internet connection

Zotero Desktop does not need to be running. ZotMD reads the Zotero Web API.

## 1. Install

```bash
uv python install 3.13
uv tool install zotmd
```

## 2. Configure

```bash
zotmd config
```

Enter:

- Numeric user ID
- Read-only API key
- Obsidian references directory
- Removal behavior
- Optional state database path
- Optional custom template path

API-key input is hidden. ZotMD writes `config.toml` with owner-only permissions.

??? tip "Keep the API key out of `config.toml`"

    Export the key before setup and every later ZotMD command:

    ```bash
    export ZOTMD_API_KEY="your-read-only-key"
    zotmd config
    ```

    The environment value takes precedence and is not copied into the file.

## 3. Preview

```bash
zotmd sync --full --dry-run
```

Review:

- Creates and rewrites
- Citation-key renames
- Removals or permanent deletions
- Output-directory moves
- Missing citation keys
- Filename collisions
- Errors

A dry run reads the Web API, templates, existing notes, and state. It does not create directories or databases, write notes, move or delete files, or advance synchronization state.

## 4. Run the first sync

Back up any existing output, then run:

```bash
zotmd sync --full
```

Later updates:

```bash
zotmd sync
```

## Next

- [Configuration](configuration.md)
- [Commands and synchronization behavior](usage.md)
- [Generated notes and templates](generated_notes.md)
- [Troubleshooting](troubleshooting.md)
