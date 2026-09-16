# Configuration

Configuration for `zotmd sync` and `zotmd status`.

The Python paper-discovery API does not read this file or use synchronization state.

## Locations

| Data | macOS default | Linux default |
|---|---|---|
| Configuration | `~/Library/Application Support/zotmd/config.toml` | `~/.config/zotmd/config.toml` |
| State | `~/Library/Application Support/zotmd/sync.sqlite` | `~/.local/share/zotmd/sync.sqlite` |

Show effective paths:

```bash
zotmd status
```

## Example

```toml
[zotero]
library_id = "1234567"
api_key = "read-only-key"

[sync]
output_dir = "~/Documents/references"
deletion_behavior = "move"

[advanced]
db_path = ""
template_path = ""
```

Unknown sections and keys are rejected.

## Zotero

| Setting | Required | Value |
|---|---|---|
| `zotero.library_id` | Yes | Numeric personal-library user ID |
| `zotero.api_key` | Unless `ZOTMD_API_KEY` is set | Personal-library read-only key |

Group library IDs are not supported.

`ZOTMD_API_KEY` always takes precedence over the stored key.

## Synchronization

| Setting | Required | Value |
|---|---|---|
| `sync.output_dir` | Yes | Generated-note directory |
| `sync.deletion_behavior` | Yes | `move` or `delete` |

Changing `output_dir` moves state-managed active and removed notes after collision and permission checks. Unmanaged files remain in place.

Removal choices:

- `move`: place removed notes under `output_dir/removed/`
- `delete`: permanently delete removed notes

Use `move` unless permanent deletion is required.

## Advanced

| Setting | Default | Value |
|---|---|---|
| `advanced.db_path` | Platform state path | SQLite state file |
| `advanced.template_path` | Built-in template | Custom Jinja2 body template |

An empty string selects the default. Relative paths resolve from the directory containing `config.toml`.

See [Generated notes and templates](generated_notes.md) for frontmatter, Notes ownership, and custom-template fields.

## File and credential safety

- Atomic configuration replacement
- File mode `0600`
- API keys excluded from object representations and logs
- Local paper discovery never uses the Web API key

Keep `config.toml` out of version control and shared diagnostics.
