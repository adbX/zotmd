# ZotMD

Sync one personal Zotero library and its PDF annotations to Obsidian-ready Markdown.

## Choose a workflow

<div class="grid cards" markdown>

-   ### Synchronize notes

    Zotero Web API to Obsidian-ready Markdown

    - Source: Zotero Web API
    - Output: one Markdown note per Better BibTeX citation key
    - Updates: metadata, attachments, annotations, renames, and removals
    - Safety: read-only API key, preflight checks, mutation-free dry run
    - Zotero Desktop: not required

    [Set up synchronization](getting_started.md)

-   ### Discover papers with Python

    Zotero Desktop to frozen Python records

    - Source: Zotero Desktop's local API
    - Output: typed paper and attachment records
    - Files: already-local stored PDFs only
    - Validation: explicit SHA-256 and MD5 fingerprinting
    - Credentials and internet: not required

    [Set up paper discovery](paper_discovery.md)

</div>

## Scope

- Personal Zotero libraries only
- One-way synchronization
- No group libraries
- No PDF downloads or attachment copying
- macOS primary; other platforms best effort

Synchronization and paper discovery use different Zotero APIs. They do not share configuration or state.
