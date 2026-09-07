# Troubleshooting

## Authentication or Connection Failure

Confirm that the configured ID is the numeric user ID for a personal library and that the API key has personal-library read access. Group libraries are not supported. Create a replacement key at [Zotero settings](https://www.zotero.org/settings/keys/new) if needed.

`ZOTMD_API_KEY` overrides the stored key. Check whether an old environment value is active before replacing the configuration:

```bash
test -n "$ZOTMD_API_KEY" && printf '%s\n' "ZOTMD_API_KEY is set"
zotmd status
```

ZotMD requires internet access to the Zotero Web API. Zotero Desktop and its local API setting do not affect the connection.

## Local Paper Discovery Cannot Connect

The local paper-source API has the opposite runtime boundary from synchronization: Zotero 10 must be running, and **Settings > Advanced > Allow other applications on this computer to communicate with Zotero** must be enabled. Discovery uses no API key and needs no internet connection.

Keep Zotero's port 23119 bound to the local machine. Do not forward it over SSH or expose it through a proxy because local API reads are unauthenticated.

## A Paper PDF Is Unavailable

The `local-file-unavailable` diagnostic means Zotero reported a stored PDF path but no file exists there. This includes WebDAV attachments that Zotero has not downloaded. Open or otherwise download the attachment through Zotero Desktop, then create a new snapshot. ZotMD never authenticates to WebDAV or triggers the download itself.

Linked attachments, symbolic links, empty files, directories, malformed file URLs, MIME and extension disagreements, and multiple PDF candidates have separate blocking diagnostics. Do not pass an attachment path to another program unless `primary_pdf` is present and its explicit `fingerprint()` call succeeds.

## Items Without Citation Keys

Install Better BibTeX, refresh the item's citation key in Zotero, wait for Zotero's Web API state to update, then run `zotmd sync` again. Missing keys are reported but do not fail the synchronization. If a previously managed item loses its key, ZotMD keeps its note active and unchanged until the key returns or the item is deleted from Zotero.

## Annotations Are Missing

Annotations must exist as Zotero annotation records beneath an attachment. ZotMD fetches attachment and annotation records from the Web API and links each annotation to its own attachment key. It does not extract annotations embedded only in PDF bytes or download PDFs.

Run a full preview to compare the reported annotation count:

```bash
zotmd sync --full --dry-run
```

## Target Collision

Two citation keys can become the same safe filename after forbidden characters are removed, length limits are applied, or macOS case and Unicode aliases are considered. ZotMD refuses every affected item rather than choosing a suffix or overwriting a note.

Assign distinct Better BibTeX citation keys, then rerun the dry run. Also remove or relocate any unmanaged file occupying a planned target only after confirming its ownership.

## Managed File Is Missing

ZotMD refuses to recreate a missing managed note automatically because doing so could hide an unavailable volume and lose user Notes. Restore the file or output mount from backup. If the file was intentionally removed, archive the state database and perform a reviewed fresh full sync.

## Legacy or Incompatible State

ZotMD 0.4 refuses a 0.3 database without modifying it and rejects the old `zotero.library_type` configuration key. Archive both the database and output, then rerun configuration for the personal-library-only schema before creating fresh state:

```bash
mv "$HOME/Library/Application Support/zotmd/sync.sqlite" \
   "$HOME/Library/Application Support/zotmd/sync.0.3-backup.sqlite"
zotmd config
zotmd sync --full --dry-run
zotmd sync --full
```

Do not delete the old output. Rename it to a dated sibling backup, choose a distinct empty output for the first 0.4 run, validate the generated corpus, and require a second incremental run to be a no-op.

## Template Failure

The configured custom template must exist when configuration is loaded and must use only the documented custom context. Undefined variables are errors. Custom templates own only the body and must emit the exact Notes boundaries if user text should survive rerenders.

Temporarily set `advanced.template_path = ""` to test the built-in body. Use `zotmd -v sync --dry-run` for an error traceback without changing notes or state.

## Permission, Move, or Delete Failure

Check that the output and source parent directories are writable. ZotMD preflights operations, writes through durable temporary sibling files, refuses overwrites, and supports output moves across filesystems. It also refuses a mutation if a managed note changes after preflight. A failed operation leaves the checkpoint pending.

With `deletion_behavior = "move"`, check for an existing same-named file in `removed/`. With `delete`, restore from backup if a later external failure occurs; permanent deletion should be selected only with a current backup.

## Reporting an Issue

Run `zotmd -v sync --dry-run --no-progress` and include the error, ZotMD version, operating system, and reproduction steps in a [GitHub issue](https://github.com/adbX/zotmd/issues). Remove API keys, local paths, private titles, and annotation content before sharing output. Never attach `config.toml` or `sync.sqlite`.
