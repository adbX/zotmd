# Usage

## Commands Overview

ZotMD provides three main commands:

| Command | Purpose |
|---------|---------|
| `zotmd init` | Initialize or update configuration |
| `zotmd sync` | Synchronize your library |
| `zotmd status` | Show configuration and sync status |

## zotmd init

Interactive configuration setup. Updates existing config if already initialized.

```bash
zotmd init
```

**Options:**
- None (fully interactive)

**When to use:**
- First-time setup
- Changing output directory
- Updating API credentials
- Switching deletion behavior

**Example:**
```bash
$ zotmd init
Library ID [1234567]:
API Key [abc...xyz]:
Library Type [user]:
Output Directory [/old/path]: /Users/me/vault/references
Deletion Behavior [move]: delete
Database Path [~/.local/share/zotmd/sync.sqlite]:

Testing connection...
✓ Connected to Zotero library (version 4652)
Configuration saved!
```

## zotmd sync

Synchronize your Zotero library to Markdown files.

```bash
zotmd sync [OPTIONS]
```

**Options:**

| Flag | Description |
|------|-------------|
| `--full` | Force full re-sync of all items (slow) |
| `--no-progress` | Disable progress bar |
| `-v, --verbose` | Show detailed logging |

### Sync Behavior

**Default (Incremental Sync):**
- Only processes changed items since last sync
- Fast (seconds to minutes)
- Detects:
    - New items
    - Modified metadata
    - New/changed annotations
    - Deleted items

**Full Sync (`--full`):**
- Re-processes entire library
- Slow (minutes to hours for large libraries)
- Use when:
    - First sync
    - Template changed
    - Database corrupted
    - Manual verification needed

### Examples

```bash
# Regular incremental sync (recommended)
zotmd sync

# Force full resync
zotmd sync --full

# Sync without progress bar (good for scripts/cron)
zotmd sync --no-progress

# Verbose output for debugging
zotmd sync --verbose
```

### What Gets Synced

For each Zotero item with a citation key:

1. **Metadata**: Title, authors, year, tags, DOI, etc.
2. **PDF Annotations**: Highlights, notes, and comments
3. **User Notes**: Preserved in `%% begin notes %%` section
4. **Frontmatter**: YAML metadata for Obsidian

**Skipped items:**
- Items without Better BibTeX citation keys
- Attachments (PDFs are linked, not copied)
- Notes (unless they're annotations)

### Deleted Items

When an item is deleted from Zotero:

- **`deletion_behavior: move`**: File moved to `removed/` subdirectory
- **`deletion_behavior: delete`**: File permanently deleted

## zotmd status

Show configuration and sync statistics.

```bash
zotmd status
```

**Output:**
```
ZotMD Configuration
===================

Config File: /Users/me/.config/zotmd/config.toml
Database: /Users/me/.local/share/zotmd/sync.sqlite
Output Dir: /Users/me/vault/references

Zotero Connection
-----------------
✓ Connected to library 1234567 (version 4652)

Sync Statistics
---------------
Last Full Sync: 2025-12-20 14:30
Last Incremental Sync: 2025-12-26 09:15
Total Items Synced: 243
Total Annotations: 89
Items Removed: 5
```

**When to use:**
- Verify configuration
- Check connection status
- View sync history
- Troubleshoot issues

## Common Workflows

### Daily Sync

After adding/updating items in Zotero:

```bash
zotmd sync
```

Takes seconds to minutes, depending on changes.

### Template Customization

After modifying your template:

```bash
zotmd sync --full
```

Regenerates all files with new template.

### Scheduled Sync (macOS)

Create a LaunchAgent to sync automatically:

```xml
<!-- ~/Library/LaunchAgents/com.zotmd.sync.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zotmd.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/zotmd</string>
        <string>sync</string>
        <string>--no-progress</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer> <!-- Every hour -->
</dict>
</plist>
```

Load with:
```bash
launchctl load ~/Library/LaunchAgents/com.zotmd.sync.plist
```

### Scheduled Sync (Linux/cron)

Edit crontab:
```bash
crontab -e
```

Add line:
```cron
0 * * * * /home/user/.local/bin/zotmd sync --no-progress
```

Syncs every hour.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 3 | Zotero connection error |

Useful for scripts:
```bash
if zotmd sync --no-progress; then
    echo "Sync successful"
else
    echo "Sync failed with code $?"
fi
```
