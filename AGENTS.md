# AGENTS.md

ZotMD 0.5.1 synchronizes one personal Zotero library to generated Markdown notes and exposes a separate immutable local paper-source API. Group libraries, linked-file copying, and bidirectional synchronization are out of scope.

## Development

Use `uv` for the environment and commands:

```bash
uv sync --locked --all-groups
uv run --frozen pytest tests --cov=src/zotmd --cov-report=term-missing --cov-fail-under=80
uv run --frozen ruff format --check src tests tools
uv run --frozen ruff check src tests tools
uv run --frozen mypy src
uv run --frozen rumdl check README.md CHANGELOG.md ROADMAP.md SECURITY.md docs tests/fixtures/rendered
uv run --frozen --group docs zensical build --clean
```

These commands mirror `.github/workflows/tests.yml`, which is the canonical check procedure.

The package supports Python 3.13 and 3.14. User documentation lives in `docs/` and is built with Zensical.

## Release Contracts

- Configuration uses a closed TOML schema. `ZOTMD_API_KEY` overrides the stored key, and credential fields must never appear in object representations or logs.
- `ZoteroClient` always constructs Pyzotero for a personal `user` library and the synchronization path calls only read APIs.
- ZotMD 0.4 requires fresh schema-version-4 state. It does not migrate 0.3 state or accept the old `zotero.library_type` key.
- Dry runs may read the Web API, templates, state, and notes, but must not mutate local state or report actions beyond a blocking output relocation.
- Managed-note identity and content are pinned between preflight and mutation. A concurrent change must be preserved and must leave the checkpoint pending.
- Publication titles are nonblank and normalized to one line before any template sees them. Custom body templates should use the HTML-escaped `title` context value for headings.
- ZotMD owns canonical frontmatter. A custom Jinja template controls only the body and receives `item`, `title`, sorted `annotations`, and `preserved_notes`.
- Template hashes cover the selected template and only its recursive static `include`, `extends`, and `import` dependencies. Rendering a template change still fetches current annotations and attachments from Zotero before rerendering active notes from cached top-level item JSON.
- User text is preserved only between `<!-- zotmd:notes:start -->` and `<!-- zotmd:notes:end -->`. Old percent-style or generic begin/end markers are not recognized.
- A managed item that loses its citation key remains active and unchanged. It follows removal behavior only after Zotero reports the item deleted.
- `iter_papers()` uses only Zotero 10's loopback local API. It loads no ZotMD configuration or state, requests no credential or write authorization, and returns no partial snapshot.
- Paper discovery handles only already-local stored PDFs. The ZotMD process does not contact WebDAV, download files, follow symlinks, retain or expose note or annotation content, or read PDF bytes before `fingerprint()`. Zotero Desktop may perform its own attachment hash while serializing local API metadata.
- Local item versions are scoped by `Zotero-Server-ID`; stable snapshots require matching raw start and end version and server headers.

## Packaging

`uv build --no-sources` builds the wheel through the source distribution. Release checks inspect both archives, import the installed wheel from its isolated environment, exercise the CLI, and run a synchronization test against the installed package.
