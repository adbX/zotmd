"""Sanitize citation keys and filenames for safe filesystem operations."""

import re


class FilenameSanitizer:
    """Sanitizes citation keys and filenames for cross-platform compatibility."""

    # Forbidden characters in filenames (Windows + Unix)
    FORBIDDEN_CHARS = r'[<>:"/\\|?*\x00-\x1f]'

    # Maximum filename length (conservative limit for all filesystems)
    MAX_FILENAME_LENGTH = 255

    @staticmethod
    def sanitize(citation_key: str, replacement: str = "") -> str:
        """
        Remove forbidden characters from citation key to create safe filename.

        Args:
            citation_key: Citation key to sanitize
            replacement: Character to replace forbidden chars with (default: empty string)

        Returns:
            Sanitized filename safe for all filesystems

        Examples:
            >>> FilenameSanitizer.sanitize('smith:2020')
            'smith2020'

            >>> FilenameSanitizer.sanitize('file/name*test', '_')
            'file_name_test'

            >>> FilenameSanitizer.sanitize('a' * 300)[:10]
            'aaaaaaaaaa'
        """
        if not citation_key:
            return ""

        # Remove forbidden characters
        sanitized = re.sub(FilenameSanitizer.FORBIDDEN_CHARS, replacement, citation_key)

        # Replace spaces with underscores (optional, but cleaner)
        sanitized = sanitized.replace(" ", "_")

        # Remove leading/trailing dots and spaces (problematic on Windows)
        sanitized = sanitized.strip(". ")

        # Limit length to MAX_FILENAME_LENGTH
        # Reserve 3 chars for ".md" extension
        max_length = FilenameSanitizer.MAX_FILENAME_LENGTH - 3
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]

        # Ensure not empty after sanitization
        if not sanitized:
            return "untitled"

        return sanitized

    @staticmethod
    def validate(filename: str) -> bool:
        """
        Check if filename is valid and safe.

        Args:
            filename: Filename to validate

        Returns:
            True if valid, False otherwise
        """
        if not filename or not isinstance(filename, str):
            return False

        # Check for empty or whitespace-only
        if not filename.strip():
            return False

        # Check for forbidden characters
        if re.search(FilenameSanitizer.FORBIDDEN_CHARS, filename):
            return False

        # Check length
        if len(filename) > FilenameSanitizer.MAX_FILENAME_LENGTH:
            return False

        # Check for problematic names
        if filename in [".", ".."]:
            return False

        # Check for leading/trailing dots or spaces
        if filename != filename.strip(". "):
            return False

        return True

    @staticmethod
    def add_extension(citation_key: str, extension: str = "md") -> str:
        """
        Sanitize citation key and add file extension.

        Args:
            citation_key: Citation key to sanitize
            extension: File extension (default: 'md')

        Returns:
            Sanitized filename with extension

        Examples:
            >>> FilenameSanitizer.add_extension('smith2020')
            'smith2020.md'

            >>> FilenameSanitizer.add_extension('test:file', 'txt')
            'testfile.txt'
        """
        sanitized = FilenameSanitizer.sanitize(citation_key)

        # Ensure extension doesn't have leading dot
        extension = extension.lstrip(".")

        return f"{sanitized}.{extension}"

    @staticmethod
    def sanitize_with_dedup(citation_key: str, existing_keys: set[str]) -> str:
        """
        Sanitize citation key and ensure uniqueness by adding suffix if needed.

        Args:
            citation_key: Citation key to sanitize
            existing_keys: Set of already-used citation keys

        Returns:
            Unique sanitized citation key

        Examples:
            >>> FilenameSanitizer.sanitize_with_dedup('smith2020', {'smith2020'})
            'smith2020-2'

            >>> FilenameSanitizer.sanitize_with_dedup('smith2020', {'smith2020', 'smith2020-2'})
            'smith2020-3'
        """
        sanitized = FilenameSanitizer.sanitize(citation_key)

        if sanitized not in existing_keys:
            return sanitized

        # Find unique suffix
        counter = 2
        while f"{sanitized}-{counter}" in existing_keys:
            counter += 1

        return f"{sanitized}-{counter}"
