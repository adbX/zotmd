# Getting Started

This guide walks you through setting up ZotMD for the first time.

## Step 1: Install Better BibTeX

Better BibTeX is a Zotero plugin that generates citation keys for your library items.

1. Download from [retorque.re/zotero-better-bibtex](https://retorque.re/zotero-better-bibtex/)
2. In Zotero: **Tools → Add-ons → Install Add-on From File**
3. Select the downloaded `.xpi` file
4. Restart Zotero

**Verify:** Right-click any item → **Better BibTeX → Refresh BibTeX key**

## Step 2: Enable Zotero API Access

1. Open Zotero Settings → **Advanced** → **Miscellaneous**
2. Check **"Allow other applications to access Zotero"**
3. Click **OK**

## Step 3: Get Your Credentials

### Library ID

1. Go to [zotero.org/settings/keys](https://www.zotero.org/settings/keys)
2. Find **"Your userID for use in API calls"**
3. Copy the number (e.g., `1234567`)

### API Key

1. Go to [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new)
2. Enter a description (e.g., "ZotMD Sync")
3. Under **Personal Library**, check:
   - ✓ Allow library access
   - ✓ Read Only
4. Click **Save Key**
5. **Copy the generated key** (you won't see it again!)

## Step 4: Initialize Configuration

Run the interactive setup:

```bash
zotmd init
```

You'll be prompted for:

```
Zotero MD Sync - Configuration
==============================

Library ID []: 1234567
API Key []: abc123xyz789...
Library Type (user/group) [user]:
Output Directory []: /Users/yourname/notes/references
Deletion Behavior (move/delete) [move]:
Database Path (Enter for default) [~/.local/share/zotmd/sync.sqlite]:

Testing connection...
✓ Connected to Zotero library (version 4652)

Configuration saved to ~/.config/zotmd/config.toml
```

### Configuration Options

- **Library ID**: Your numeric user ID from Zotero
- **API Key**: The key you generated above
- **Library Type**: `user` (personal library) or `group` (shared library)
- **Output Directory**: Where to save Markdown files
- **Deletion Behavior**:
    - `move`: Deleted items moved to `removed/` subdirectory
    - `delete`: Deleted items permanently removed
- **Database Path**: Leave blank for default location

## Step 5: Run Your First Sync

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

## Step 6: Verify the Results

Check your output directory:

```bash
ls ~/notes/references
```

You should see files named after their citation keys:

```
smith2020introduction.md
jones2019methodology.md
wilson2021analysis.md
...
```

## Next Steps

- Learn about [Commands](usage.md) for daily use
- Customize your [Configuration](configuration.md)
- See [Troubleshooting](troubleshooting.md) if you encounter issues

## Updating Existing Config

To change your configuration later, simply run `zotmd init` again. Press **Enter** to keep existing values, or type a new value to update.

```bash
zotmd init
```

```
Library ID [1234567]:  # Press Enter to keep
API Key [abc...xyz]:   # Press Enter to keep
Output Directory [/old/path]: /new/path  # Type new value
```
