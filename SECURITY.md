# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.5.x | Yes |
| 0.4.x | Yes |
| 0.3.x and earlier | No |

## Reporting a vulnerability

Report suspected vulnerabilities through [GitHub private vulnerability reporting](https://github.com/adbX/zotmd/security/advisories/new). Do not disclose an unpatched vulnerability in a public issue.

Include the affected ZotMD version, operating system, impact, reproduction steps, and any suggested mitigation. Remove API keys, local paths, state databases, private library records, and generated notes before submitting evidence.

Zotero Desktop's local API permits unauthenticated reads. Keep port 23119 bound to loopback and never forward or expose it to another machine. ZotMD's paper-source API requests no local write authorization, contacts no WebDAV server, and omits enclosure URIs and local paths from record representations and diagnostics.
