"""File manager for markdown file operations."""

import logging
from pathlib import Path
from typing import Optional
import shutil

from ..utils.filename_sanitizer import FilenameSanitizer


logger = logging.getLogger(__name__)


class FileManager:
    """Manages markdown file operations (create, update, move)."""

    def __init__(self, base_dir: Path, deletion_behavior: str = "move"):
        """
        Initialize file manager.

        Args:
            base_dir: Base directory for markdown files (e.g., references/)
            deletion_behavior: How to handle removed items - "move" or "delete"
        """
        self.base_dir = Path(base_dir)
        self.deletion_behavior = deletion_behavior

        # Only create removed_dir if using "move" behavior
        if deletion_behavior == "move":
            self.removed_dir: Optional[Path] = self.base_dir / "removed"
            self.removed_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.removed_dir = None

        # Create base directory if it doesn't exist
        self.base_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"FileManager initialized: base={self.base_dir}, deletion={deletion_behavior}"
        )

    def get_file_path(self, citation_key: str) -> Path:
        """
        Get file path for a citation key.

        Args:
            citation_key: Citation key

        Returns:
            Path to markdown file
        """
        filename = FilenameSanitizer.add_extension(citation_key, "md")
        return self.base_dir / filename

    def file_exists(self, citation_key: str) -> bool:
        """
        Check if markdown file exists.

        Args:
            citation_key: Citation key

        Returns:
            True if file exists
        """
        file_path = self.get_file_path(citation_key)
        return file_path.exists()

    def read_existing(self, citation_key: str) -> Optional[str]:
        """
        Read existing markdown file if it exists.

        Args:
            citation_key: Citation key

        Returns:
            File content or None if doesn't exist
        """
        file_path = self.get_file_path(citation_key)

        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            logger.debug(f"Read existing file: {file_path}")
            return content

        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return None

    def write_markdown(self, citation_key: str, content: str) -> Path:
        """
        Write markdown file (create or update).

        Args:
            citation_key: Citation key
            content: Markdown content to write

        Returns:
            Path to written file

        Raises:
            IOError: If write fails
        """
        file_path = self.get_file_path(citation_key)

        try:
            # Write to file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Wrote markdown file: {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"Failed to write file {file_path}: {e}")
            raise IOError(f"Failed to write markdown file: {e}") from e

    def handle_removed_item(self, citation_key: str) -> Optional[Path]:
        """
        Handle a removed item based on configured deletion behavior.

        Args:
            citation_key: Citation key

        Returns:
            Path to moved file (if moved) or None
        """
        if self.deletion_behavior == "move":
            return self.move_to_removed(citation_key)
        else:
            self.delete_file(citation_key)
            return None

    def move_to_removed(self, citation_key: str) -> Optional[Path]:
        """
        Move markdown file to removed/ directory.

        Args:
            citation_key: Citation key

        Returns:
            Path to moved file or None if file doesn't exist
        """
        source_path = self.get_file_path(citation_key)

        if not source_path.exists():
            logger.warning(f"Cannot move non-existent file: {source_path}")
            return None

        if self.removed_dir is None:
            logger.warning("Cannot move file: removed_dir not configured")
            return None

        # Destination path
        filename = FilenameSanitizer.add_extension(citation_key, "md")
        dest_path = self.removed_dir / filename

        # Handle name conflicts in removed directory
        if dest_path.exists():
            # Add timestamp to avoid overwriting
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = dest_path.stem
            dest_path = self.removed_dir / f"{stem}_{timestamp}.md"

        try:
            # Move file
            shutil.move(str(source_path), str(dest_path))
            logger.info(f"Moved file to removed: {source_path} -> {dest_path}")
            return dest_path

        except Exception as e:
            logger.error(f"Failed to move file {source_path}: {e}")
            return None

    def delete_file(self, citation_key: str) -> bool:
        """
        Delete markdown file.

        Args:
            citation_key: Citation key

        Returns:
            True if deleted, False if doesn't exist or deletion failed
        """
        file_path = self.get_file_path(citation_key)

        if not file_path.exists():
            logger.warning(f"Cannot delete non-existent file: {file_path}")
            return False

        try:
            file_path.unlink()
            logger.info(f"Deleted file: {file_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False

    def list_all_files(self) -> list[Path]:
        """
        List all markdown files in base directory.

        Returns:
            List of markdown file paths
        """
        return sorted(self.base_dir.glob("*.md"))

    def list_removed_files(self) -> list[Path]:
        """
        List all markdown files in removed directory.

        Returns:
            List of removed markdown file paths
        """
        return sorted(self.removed_dir.glob("*.md"))
