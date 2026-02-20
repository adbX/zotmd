# Getting Started

??? note "Prerequisites"

    ??? info "Ensure the Better BibTeX Zotero plugin is installed"

        1. Download from [retorque.re/zotero-better-bibtex](https://retorque.re/zotero-better-bibtex/)
        2. In Zotero: **Tools -> Add-ons -> Install Add-on From File**
        3. Select the downloaded `.xpi` file
        4. Restart Zotero and verify by right-clicking any item -> **Better BibTeX -> Refresh BibTeX key**

    ??? info "Ensure Zotero API access is enabled"

        - Open Zotero Settings -> **Advanced** -> **Miscellaneous**
        - Check **"Allow other applications to access Zotero"**
        - Click **OK**

## 1. Install ZotMD using uv (recommended) or pipx

=== "uv"

    ```bash
    # Install with uv https://docs.astral.sh/uv/
    uv tool install zotmd
    ```

=== "pipx"

    ```bash
    # Install with pipx https://pipx.pypa.io/
    pipx install zotmd
    ```

## 2. Get your API keys: [zotero.org/settings/keys](https://www.zotero.org/settings/keys)

??? info "Library ID"

    - Go to [zotero.org/settings/keys](https://www.zotero.org/settings/keys)
    - Find *"Your userID for use in API calls"*
    - **Copy the number** (e.g., `1234567`) for the next step

??? info "API Key"

    - Click on [Create a new private key](https://www.zotero.org/settings/keys/new) under *Applications*
    - Enter a description (e.g., "ZotMD Sync")
    - Under *Personal Library*, the defaults are OK (*Personal Library -> Allow library access, Default Group Permissions -> None*)
    - Click *Save Key*
    - **Copy the generated key** (you won't see it again!)

## 3. Configure ZotMD

??? warning "Keep Zotero running while syncing"

Run the interactive setup:

```bash
zotmd config
```

You'll be prompted for:

```
ZotMD - Configuration
===================================
Get your Library ID and API Key at:
  https://www.zotero.org/settings/keys

Library ID: 1234567
API Key: abc123xyz789...
Library Type (user/group) [default: user]:
Output Directory: /YourObsidianVault/research/references
Deletion Behavior (move/delete) [default: move]:
Database Path (Enter for default) [default: ~/.local/share/zotmd/sync.sqlite]:

Testing connection to Zotero...
Connected successfully (library version 4652)

Configuration saved to ~/.config/zotmd/config.toml
```

??? question "Configuration Options"

    - **Library ID**: Your numeric user ID from Zotero
    - **API Key**: The key you generated above
    - **Library Type**: `user` (personal library) or `group` (shared library)
    - **Output Directory**: Where to save Markdown files
    - **Deletion Behavior**: How generated Markdown files whose corresponding Zotero articles are deleted are handled
        - `move`: Deleted items moved to `removed/` subdirectory
        - `delete`: Deleted items permanently removed
    - **Database Path**: Leave blank for default location

## 4. Run your first sync

```bash
zotmd sync --full
```

This performs a full sync of your entire library. You'll see:

```
Syncing Zotero library...
Processing: 243 items |████████████████████| 100%
✓ Synced 243 items (15 new, 228 updated)
✓ Extracted 89 annotations
✓ Completed in 45s
```

Your Markdown files are now in your configured output directory!

## Next Steps

- [Troubleshooting](troubleshooting.md)
- [Usage & Commands](usage.md)
