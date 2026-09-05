# ZotMD

ZotMD synchronizes a personal Zotero library and its PDF annotations to Obsidian-native Markdown. It reads metadata and annotations through the Zotero Web API, writes one note per item with a Better BibTeX citation key, and preserves user text inside an explicit Notes region.

## Requirements

- macOS and Python 3.13 or newer. Other platforms are best effort.
- A personal Zotero library. Group libraries are not supported.
- [Better BibTeX](https://retorque.re/zotero-better-bibtex/) citation keys.
- A dedicated [Zotero API key](https://www.zotero.org/settings/keys/new) with personal-library read access and no write access.
- Internet access during synchronization. Zotero Desktop does not need to be running.

## Install

Install ZotMD with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install zotmd
zotmd config
zotmd sync --full --dry-run
zotmd sync --full
```

Run `zotmd sync` for subsequent incremental synchronizations. ZotMD detects metadata changes, child-only annotation and attachment changes, citation-key renames, and removals.

## Credentials

Interactive setup can store the API key in the owner-only configuration file. To keep it out of the file, set it in the environment before setup and future commands:

```bash
export ZOTMD_API_KEY="your-read-only-key"
zotmd config
```

`ZOTMD_API_KEY` takes precedence over a stored key and is never copied into the configuration file by setup.

## Generated Notes

ZotMD owns canonical YAML frontmatter and all generated body content except text between these boundaries:

```markdown
## Notes
<!-- zotmd:notes:start -->
Your notes remain here.
<!-- zotmd:notes:end -->

## Annotations
```

Only content inside the boundaries is preserved on later syncs. Each annotation links to its own Zotero attachment. Attachments and PDFs are linked, not copied.

## Safety

`zotmd sync --dry-run` performs Web API and local reads but does not create directories, migrate state, write notes, move files, delete files, or advance checkpoints. Any malformed API record, target collision, rendering error, filesystem error, or state error produces exit status 1 and leaves the library checkpoint pending.

ZotMD 0.4 requires fresh state and does not accept the old `zotero.library_type` setting. If upgrading from 0.3, rename the old output directory as a backup or select a distinct empty output directory, archive the old `sync.sqlite`, and rerun `zotmd config` to rewrite `config.toml` for a personal library before starting a fresh full sync. Do not delete the old notes first, and keep the backups until the rebuilt library has been checked.

## Documentation

See the [ZotMD documentation](https://adbX.github.io/zotmd/) for setup, configuration, template context, generated metadata, commands, and troubleshooting.

## License

ZotMD is available under the [MIT License](LICENSE).
