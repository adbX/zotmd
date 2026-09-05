"""Zotero to Markdown synchronization tool."""

from importlib.metadata import version as _distribution_version

__version__ = _distribution_version("zotmd")

__all__ = ["__version__"]
