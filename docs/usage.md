# Commands

## Command list

| Command | Purpose |
|---|---|
| `zotmd config` | Create or update configuration |
| `zotmd init` | Alias for `zotmd config` |
| `zotmd sync` | Synchronize incrementally |
| `zotmd status` | Test connectivity and show read-only state statistics |

Verbose logging precedes the command:

```bash
zotmd -v sync
```

## Sync options

```text
zotmd sync [--full] [--dry-run] [--no-progress]
```

| Option | Effect |
|---|---|
| `--full` | Fetch and rerender every eligible top-level item |
| `--dry-run` | Report planned work without changing files or state |
| `--no-progress` | Suppress progress displays for scripts and logs |

## Common runs

Preview an incremental sync:

```bash
zotmd sync --dry-run
```

Apply it:

```bash
zotmd sync
```

Preview and apply a complete rerender:

```bash
zotmd sync --full --dry-run
zotmd sync --full
```

Plain output for automation:

```bash
zotmd sync --no-progress
```

## Incremental behavior

ZotMD detects:

- Top-level metadata changes
- Added, edited, or deleted annotations
- Attachment-only changes
- Better BibTeX citation-key renames
- Deleted Zotero items
- Template changes

Web API calls remain serial and follow Zotero's server-provided backoff and retry instructions.

## Results and failures

Output counts:

- Processed and skipped items
- Created, updated, and renamed notes
- Moved or permanently deleted notes
- Relocated output files
- Annotations
- Missing citation keys
- Collisions and errors

Missing citation keys are nonfatal skips. Previously managed items that lose a key remain active and unchanged.

Exit status 1:

- Malformed API or cached record
- Sanitized, case-insensitive, or Unicode-normalized filename collision
- Template rendering error
- Missing managed file
- Permission or filesystem error
- Managed note changed after preflight
- Failed move, write, removal, deletion, or state update

Successful item work may remain after a partial failure. The library and template checkpoints remain pending, so the next run retries the incomplete interval.

## Removals and renames

With `deletion_behavior = "move"`:

- Preflight source and destination
- Move the note to `removed/`
- Refuse overwrites

With `deletion_behavior = "delete"`:

- Delete the exact state-managed path
- Record success only after deletion

After a citation-key change:

- Read the stored old path
- Preserve the Notes area
- Claim the sanitized new target
- Refuse overwrites
- Update state after the rename succeeds

## Status

`zotmd status`:

- Tests the Web API connection
- Opens existing SQLite state read-only
- Shows configuration paths
- Counts active and removed items and annotations
- Shows synchronization times and the last completed library version
- Never creates or migrates a database

## Exit status

| Status | Meaning |
|---|---|
| 0 | Completed without actionable errors |
| 1 | Configuration, connection, synchronization, or partial-sync failure |
| 2 | Invalid command syntax or options |
