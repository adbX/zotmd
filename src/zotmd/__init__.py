"""Zotero to Markdown synchronization tool."""

from importlib.metadata import version as _distribution_version

from .models.paper import (
    AttachmentAvailability,
    Creator,
    Diagnostic,
    FileFingerprint,
    Identifier,
    Paper,
    PdfAttachment,
    Tag,
)
from .paper_source import iter_papers

__version__ = _distribution_version("zotmd")

__all__ = [
    "__version__",
    "AttachmentAvailability",
    "Creator",
    "Diagnostic",
    "FileFingerprint",
    "Identifier",
    "Paper",
    "PdfAttachment",
    "Tag",
    "iter_papers",
]
