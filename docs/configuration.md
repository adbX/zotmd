# Configuration

ZotMD uses a TOML configuration file stored in your system's config directory.

## Config File Location

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/zotmd/config.toml` |
| Linux | `~/.config/zotmd/config.toml` |
| Windows | `%APPDATA%\zotmd\config.toml` |

## Configuration Schema

```toml
[zotero]
library_id = "1234567"
api_key = "abc123xyz789..."
library_type = "user"

[sync]
output_dir = "/Users/yourname/notes/references"
deletion_behavior = "move"

[advanced]
db_path = ""
template_path = ""
```

## Zotero Section

### library_id
- **Type**: String (numeric)
- **Required**: Yes
- **Description**: Your Zotero user ID or group ID
- **Find it**: [zotero.org/settings/keys](https://www.zotero.org/settings/keys)

### api_key
- **Type**: String
- **Required**: Yes
- **Description**: Your Zotero API key
- **Generate**: [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new)
- **Permissions needed**: Read Only, Allow library access

### library_type
- **Type**: String
- **Required**: Yes
- **Options**: `"user"` or `"group"`
- **Description**:
    - `"user"`: Your personal library
    - `"group"`: A shared group library

## Sync Section

### output_dir
- **Type**: String (path)
- **Required**: Yes
- **Description**: Directory where Markdown files will be saved
- **Examples**:
    - `/Users/yourname/vault/references`
    - `C:\Users\YourName\Documents\References`
    - `~/Dropbox/Notes/Zotero`

### deletion_behavior
- **Type**: String
- **Required**: Yes
- **Options**: `"move"` or `"delete"`
- **Description**:
    - `"move"`: Deleted items moved to `removed/` subdirectory
    - `"delete"`: Deleted items permanently removed from filesystem

**Recommendation:** Use `"move"` to prevent accidental data loss.

## Advanced Section

Both fields are optional. Leave empty (`""`) to use defaults.

### db_path
- **Type**: String (path)
- **Default**: Platform-specific data directory
- **Description**: Custom location for sync database
- **Default locations**:
    - macOS: `~/Library/Application Support/zotmd/sync.sqlite`
    - Linux: `~/.local/share/zotmd/sync.sqlite`
    - Windows: `%LOCALAPPDATA%\zotmd\sync.sqlite`

### template_path
- **Type**: String (path)
- **Default**: Built-in template
- **Description**: Path to custom Jinja2 template file
- **See**: [Template Customization](#template-customization) below

## Example Configurations

### Minimal (recommended for most users)
```toml
[zotero]
library_id = "1234567"
api_key = "abc123xyz789..."
library_type = "user"

[sync]
output_dir = "/Users/me/vault/references"
deletion_behavior = "move"

[advanced]
db_path = ""
template_path = ""
```

### Group Library
```toml
[zotero]
library_id = "9876543"
api_key = "def456uvw..."
library_type = "group"  # Changed to group

[sync]
output_dir = "/Users/me/shared-refs"
deletion_behavior = "move"

[advanced]
db_path = ""
template_path = ""
```

### Custom Locations
```toml
[zotero]
library_id = "1234567"
api_key = "abc123xyz..."
library_type = "user"

[sync]
output_dir = "/custom/output/path"
deletion_behavior = "delete"  # Permanent deletion

[advanced]
db_path = "/custom/db/location/sync.sqlite"
template_path = "/custom/templates/my-template.md.j2"
```

## Template Customization

ZotMD uses Jinja2 templates to generate Markdown files.

### Using a Custom Template

1. Copy the default template:
   ```bash
   # Find built-in template location
   python -c "import zotmd; print(zotmd.__file__)"
   # Built-in is at: .../zotmd/templates/default.md.j2
   ```

2. Create your custom template:
   ```bash
   cp /path/to/default.md.j2 ~/my-custom-template.md.j2
   ```

3. Edit `config.toml`:
   ```toml
   [advanced]
   template_path = "/Users/me/my-custom-template.md.j2"
   ```

4. Re-sync with new template:
   ```bash
   zotmd sync --full
   ```

### Available Template Variables

| Variable | Type | Description |
|----------|------|-------------|
| `item.title` | str | Item title |
| `item.authors` | list | Author names |
| `item.year` | str | Publication year |
| `item.item_type` | str | Zotero item type |
| `item.tags` | list | Tag strings |
| `item.citation_key` | str | Better BibTeX citation key |
| `item.abstract` | str | Abstract text |
| `item.doi` | str | DOI |
| `item.url` | str | URL |
| `item.publication_title` | str | Journal/book title |
| `annotations` | list | PDF annotations |
| `last_import` | str | Timestamp of sync |

### Template Example

```jinja2
---
title: "{{ item.title }}"
authors: {% for creator in item.creators %}{{ creator.lastName }}{% if not loop.last %}, {% endif %}{% endfor %}
year: {{ item.date[:4] if item.date else '' }}
tags: {% for tag in item.tags %}- {{ tag }}
{% endfor %}
citationKey: {{ item.citation_key }}
---

# {{ item.title }}

{% if item.abstract %}
## Abstract
{{ item.abstract }}
{% endif %}

{% if annotations %}
## Annotations
{% for annot in annotations %}
### Page {{ annot.page_label }} ({{ annot.color_category }})
{% if annot.text %}
> {{ annot.text }}
{% endif %}
{% if annot.comment %}
{{ annot.comment }}
{% endif %}
{% endfor %}
{% endif %}

## Notes
<!-- Add your notes below -->
```

## Editing Configuration

### Option 1: Use zotmd init (recommended)
```bash
zotmd init
```

Interactive prompts with current values shown.

### Option 2: Edit file directly
```bash
# macOS
open ~/.config/zotmd/config.toml

# Linux
nano ~/.config/zotmd/config.toml

# Windows
notepad %APPDATA%\zotmd\config.toml
```

After editing, verify with:
```bash
zotmd status
```

## Troubleshooting Config Issues

### Config not found
```bash
$ zotmd sync
Error: Configuration not found. Run 'zotmd init' first.
```

**Solution:** Run `zotmd init` to create config file.

### Invalid API key
```bash
$ zotmd init
Testing connection...
✗ Error: Invalid API key
```

**Solutions:**
- Regenerate API key at [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new)
- Ensure "Allow library access" is checked
- Check for typos (keys are case-sensitive)

### Invalid library ID
```bash
✗ Error: Library not found (403 Forbidden)
```

**Solutions:**
- Verify library ID at [zotero.org/settings/keys](https://www.zotero.org/settings/keys)
- Ensure library_type matches (user vs group)
- For groups, ensure you're a member

### Permission denied (output directory)
```bash
Error: Permission denied: /restricted/path
```

**Solutions:**
- Choose a directory you have write access to
- Create directory first: `mkdir -p ~/notes/references`
- Check permissions: `ls -ld ~/notes/references`
