# Installation

## Recommended: uv

[uv](https://docs.astral.sh/uv/) is the fastest and most modern Python package installer.

```bash
# Install as a tool (isolated environment)
uv tool install zotmd

# Upgrade to latest version
uv tool upgrade zotmd

# Uninstall
uv tool uninstall zotmd
```

## Alternative: pipx

[pipx](https://pipx.pypa.io/) installs Python applications in isolated environments.

```bash
# Install
pipx install zotmd

# Upgrade
pipx upgrade zotmd

# Uninstall
pipx uninstall zotmd
```

## Alternative: pip

You can also install with pip, but we recommend using `uv` or `pipx` for better isolation.

```bash
# Install globally (not recommended)
pip install zotmd

# Install in a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install zotmd
```

## Verify Installation

After installation, verify that `zotmd` is available:

```bash
zotmd --help
```

You should see the help message with available commands.

## Requirements

- **Python**: 3.13 or later
- **Better BibTeX**: Zotero plugin (required)
- **Zotero API Access**: Enabled in Zotero settings

## Next Steps

Continue to [Getting Started](getting-started.md) to set up your configuration.
