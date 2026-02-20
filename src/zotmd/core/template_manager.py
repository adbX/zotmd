"""Template change detection and versioning."""

import hashlib
from pathlib import Path
from typing import Optional
import logging

from .state_manager import TemplateVersion


logger = logging.getLogger(__name__)


class TemplateChangeDetector:
    """Detects if template has changed since last sync."""

    @staticmethod
    def compute_template_hash(template_content: str) -> str:
        """
        Compute SHA256 hash of template content.

        Args:
            template_content: Template source string

        Returns:
            SHA256 hash as hex string
        """
        return hashlib.sha256(template_content.encode("utf-8")).hexdigest()

    @staticmethod
    def get_template_identifier(template_path: Optional[Path]) -> str:
        """
        Get identifier for template (path or 'built-in').

        Args:
            template_path: Path to custom template or None for built-in

        Returns:
            "built-in" or absolute path as string
        """
        if template_path:
            return str(template_path.resolve())
        return "built-in"

    @staticmethod
    def has_template_changed(
        current_hash: str,
        current_path: str,
        stored_version: Optional[TemplateVersion],
    ) -> bool:
        """
        Check if template has changed since last recorded version.

        Args:
            current_hash: Current template hash
            current_path: Current template path identifier
            stored_version: Previously stored template version

        Returns:
            True if template changed or no stored version exists
        """
        if not stored_version:
            logger.info("No stored template version found (first sync or upgrade)")
            return False  # Don't trigger re-render on first sync

        if stored_version.template_hash != current_hash:
            logger.warning(
                f"Template content changed: {stored_version.template_hash[:8]}... "
                f"→ {current_hash[:8]}..."
            )
            return True

        if stored_version.template_path != current_path:
            logger.warning(
                f"Template path changed: {stored_version.template_path} "
                f"→ {current_path}"
            )
            return True

        return False
