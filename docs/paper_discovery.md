# Discover local papers

Use Zotero Desktop as a read-only source for tagged papers and already-local PDFs.

## Requirements

- Zotero 10 running
- Local API enabled in **Settings > Advanced**
- One exact manual tag on each selected top-level item
- PDFs already downloaded by Zotero
- Python 3.13 or newer

No Zotero Web API key. No internet connection.

## Add ZotMD to your project

```bash
uv add zotmd
```

`uv tool install zotmd` installs the CLI in an isolated environment. A Python project that imports ZotMD needs its own dependency.

## Select papers in Zotero

1. Choose a tag, such as `paper-source`.
2. Add it manually to each top-level paper.
3. Open any on-demand PDF once so Zotero stores it locally.

Automatic tags do not select papers. Apply the tag to the top-level paper, not a child attachment.

## Read one snapshot

```python
from zotmd import iter_papers

for paper in iter_papers(tag="paper-source"):
    attachment = paper.primary_pdf
    if attachment is None:
        continue

    fingerprint = attachment.fingerprint()
    print(paper.key, fingerprint.sha256)
```

`iter_papers()` returns only after ZotMD validates one complete, stable library snapshot. It closes the HTTP client before iteration begins.

`primary_pdf` is present only when the paper has one usable PDF and no blocking diagnostic. `fingerprint()` validates the file identity and reads its bytes.

## Next

- [Paper records](paper_source_api.md): imports, fields, identifiers, and ordering
- [PDFs, diagnostics, and failures](paper_files.md): eligibility, fingerprints, diagnostic codes, and exceptions
- [Troubleshooting](troubleshooting.md): connection and unavailable-file fixes
