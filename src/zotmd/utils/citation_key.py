"""Extract and validate Better BibTeX citation keys from Zotero items."""

import re
from typing import Optional


class CitationKeyExtractor:
    """Extracts Better BibTeX citation keys from Zotero item 'extra' fields."""

    # Pattern matches "Citation Key: <key>" in the extra field
    CITATION_KEY_PATTERN = re.compile(r"Citation Key:\s*([^\n]+)", re.IGNORECASE)

    @staticmethod
    def extract(item: dict) -> Optional[str]:
        """
        Extract citation key from Zotero item's 'extra' field.

        Args:
            item: Zotero item dictionary with 'data' key

        Returns:
            Citation key string if found, None otherwise

        Examples:
            >>> item = {'data': {'extra': 'Citation Key: smith2020\\nPMID: 12345'}}
            >>> CitationKeyExtractor.extract(item)
            'smith2020'

            >>> item = {'data': {'extra': 'PMID: 12345'}}
            >>> CitationKeyExtractor.extract(item)
            None
        """
        try:
            extra = item.get("data", {}).get("extra", "")
            if not extra:
                return None

            match = CitationKeyExtractor.CITATION_KEY_PATTERN.search(extra)
            if match:
                citation_key = match.group(1).strip()
                # Return only if non-empty after stripping
                return citation_key if citation_key else None

            return None

        except (KeyError, AttributeError, TypeError):
            return None

    @staticmethod
    def validate(citation_key: str) -> bool:
        """
        Validate citation key format.

        Args:
            citation_key: Citation key to validate

        Returns:
            True if valid, False otherwise

        Notes:
            Valid citation keys should:
            - Not be empty
            - Not contain newlines
            - Not contain path separators or other forbidden chars
        """
        if not citation_key or not isinstance(citation_key, str):
            return False

        # Check for empty or whitespace-only
        if not citation_key.strip():
            return False

        # Check for newlines
        if "\n" in citation_key or "\r" in citation_key:
            return False

        # Check for forbidden filesystem characters
        forbidden_chars = r'<>:"/\\|?*\x00-\x1f'
        if re.search(f"[{forbidden_chars}]", citation_key):
            return False

        return True

    @staticmethod
    def extract_and_validate(item: dict) -> Optional[str]:
        """
        Extract and validate citation key in one step.

        Args:
            item: Zotero item dictionary

        Returns:
            Valid citation key or None
        """
        citation_key = CitationKeyExtractor.extract(item)
        if citation_key and CitationKeyExtractor.validate(citation_key):
            return citation_key
        return None
