# Troubleshooting

## Synchronization cannot connect

- Confirm the numeric user ID belongs to a personal library.
- Confirm the API key has personal-library read access.
- Remove group and write access from the key.
- Check for an old environment value:

```bash
test -n "$ZOTMD_API_KEY" && printf '%s\n' "ZOTMD_API_KEY is set"
zotmd status
```

Synchronization needs internet access. Zotero Desktop and its local API setting do not affect it.

## Paper discovery cannot connect

- Start Zotero 10.
- Enable **Settings > Advanced > Allow other applications on this computer to communicate with Zotero**.
- Keep port 23119 on the local machine.

Paper discovery uses no API key and needs no internet connection. Do not forward the unauthenticated local API over SSH or expose it through a proxy.

## A paper PDF is unavailable

`local-file-unavailable` means Zotero reported a stored PDF path but the file is not local.

1. Open or download the attachment through Zotero Desktop.
2. Call `iter_papers()` again for a new snapshot.

ZotMD never authenticates to WebDAV or starts a download.

Do not pass a path to another program unless `primary_pdf` is present and `fingerprint()` succeeds.

## An item has no citation key

1. Install Better BibTeX.
2. Refresh the item's citation key in Zotero.
3. Wait for the Zotero Web API to update.
4. Run `zotmd sync` again.

A missing key does not fail synchronization. A previously managed item remains active and unchanged until the key returns or Zotero reports the item deleted.

## Annotations are missing

ZotMD reads Zotero annotation records beneath attachments. It does not extract annotations embedded only in PDF bytes.

Compare a full preview:

```bash
zotmd sync --full --dry-run
```

## Filename collision

Different citation keys can resolve to the same safe filename after:

- Forbidden-character removal
- Length limits
- macOS case folding
- Unicode normalization

ZotMD refuses every affected item. Assign distinct Better BibTeX citation keys, then rerun the dry run.

For an unmanaged file at a planned target, confirm ownership before moving or removing it.

## A managed note is missing

ZotMD does not recreate a missing managed note automatically. This avoids hiding an unavailable volume or losing user Notes.

- Restore the file or output mount from backup.
- If removal was intentional, archive the state database and run a reviewed fresh full sync.

## Custom template failure

- Confirm the configured file exists.
- Use only the [documented template context](generated_notes.md#custom-body-templates).
- Include the exact Notes markers when user text must survive.
- Use static names for `include`, `extends`, and `import`.

Test the built-in body by setting:

```toml
[advanced]
template_path = ""
```

Show a traceback without changing notes or state:

```bash
zotmd -v sync --dry-run
```

## Permission, move, or delete failure

- Check that output and source parent directories are writable.
- Check for an existing same-named file in `removed/`.
- Restore from backup after a failed permanent deletion.
- Rerun after resolving the reported error; the checkpoint remains pending.

ZotMD refuses overwrites and refuses mutation when a managed note changes after preflight.

## Report an issue

Run:

```bash
zotmd -v sync --dry-run --no-progress
```

Include:

- Error text
- ZotMD version
- Operating system
- Reproduction steps

Remove API keys, local paths, private titles, and annotation content. Never attach `config.toml` or `sync.sqlite`.

[Open a GitHub issue](https://github.com/adbX/zotmd/issues)
