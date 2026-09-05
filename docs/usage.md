# Usage

## Commands

| Command | Purpose |
|---|---|
| `zotmd config` | Create or update configuration interactively |
| `zotmd init` | Alias for `zotmd config` |
| `zotmd sync` | Reconcile the library incrementally |
| `zotmd status` | Test connectivity and show read-only state statistics |

Global verbose logging precedes the command: `zotmd -v sync`.

## Sync Options

```text
zotmd sync [--full] [--dry-run] [--no-progress]
```

| Option | Effect |
|---|---|
| `--full` | Fetch and rerender every eligible top-level item |
| `--dry-run` | Report planned work without changing files or state |
| `--no-progress` | Suppress progress displays for scripts and logs |

The default incremental operation fetches changed top-level items plus all current attachments and annotations. A deterministic child signature catches annotation additions, edits, deletions, same-count changes, and attachment-only changes even when Zotero does not return the parent as modified.

Web API calls remain serial. Pyzotero follows Zotero's server-provided backoff and retry instructions.

## Results and Failures

Sync output reports processed, created, updated, renamed, removed, permanently deleted, relocated, and skipped items. It also reports annotation totals, missing citation keys, path collisions, and errors. Dry-run counters describe planned actions.

Items without a Better BibTeX citation key are nonfatal eligibility skips. These conditions are actionable failures:

- Malformed API or cached records.
- Sanitized, case-insensitive, or Unicode-normalized target collisions.
- Template rendering failures.
- Missing managed files or filesystem permission failures.
- Managed notes changed concurrently after preflight.
- Failed moves, writes, removals, deletions, or state updates.

ZotMD can retain successful per-item work after a partial failure, but it does not advance the library or template checkpoint. The next run retries the incomplete interval. Any actionable failure returns exit status 1.

## Common Workflows

Preview a normal incremental sync:

```bash
zotmd sync --dry-run
```

Perform it after reviewing the result:

```bash
zotmd sync
```

Preview and perform a complete rerender:

```bash
zotmd sync --full --dry-run
zotmd sync --full
```

Use plain output in automation:

```bash
if zotmd sync --no-progress; then
    printf '%s\n' "ZotMD sync completed"
else
    printf '%s\n' "ZotMD sync failed" >&2
fi
```

## Removals and Renames

The default `deletion_behavior = "move"` relocates a note to `removed/` only after the source and destination pass preflight. `delete` permanently removes the actual path recorded in state. A failed operation leaves the item active and the checkpoint pending.

When a Better BibTeX citation key changes, ZotMD reads the stored old path, preserves the Notes region, claims the sanitized new target without overwriting it, and updates state only after the file operation succeeds.

## Status

`zotmd status` tests the Web API connection and opens existing SQLite state read-only. It reports configuration paths, active and removed item counts, annotation count, synchronization timestamps, and the last completed library version. It does not create or migrate a database.

## Exit Status

| Status | Meaning |
|---|---|
| 0 | The command completed without actionable errors |
| 1 | Configuration, connection, reconciliation, or partial-sync failure |
| 2 | Invalid command-line syntax or options |
