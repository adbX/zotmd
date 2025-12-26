"""Parse and format dates from Zotero API responses."""

from datetime import datetime
from typing import Optional


class DateFormatter:
    """Handles date parsing and formatting for Zotero timestamps."""

    # Zotero API uses ISO 8601 format with 'Z' suffix
    ZOTERO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

    # Obsidian property format (date only)
    OBSIDIAN_DATE_FORMAT = "%Y-%m-%d"

    # Obsidian with time (for lastImport)
    OBSIDIAN_DATETIME_FORMAT = "%Y-%m-%d %H:%M"

    @staticmethod
    def parse_zotero_date(date_str: Optional[str]) -> Optional[datetime]:
        """
        Parse Zotero ISO 8601 date string to datetime object.

        Args:
            date_str: Date string from Zotero API (e.g., '2025-12-21T11:05:00Z')

        Returns:
            datetime object or None if parsing fails

        Examples:
            >>> DateFormatter.parse_zotero_date('2025-12-21T11:05:00Z')
            datetime.datetime(2025, 12, 21, 11, 5)

            >>> DateFormatter.parse_zotero_date(None)
            None
        """
        if not date_str:
            return None

        try:
            # Handle 'Z' suffix (UTC timezone indicator)
            if date_str.endswith("Z"):
                return datetime.strptime(date_str, DateFormatter.ZOTERO_DATE_FORMAT)
            else:
                # Try ISO format without 'Z'
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def to_obsidian_date(date_obj: Optional[datetime]) -> str:
        """
        Format datetime to Obsidian date-only format (YYYY-MM-DD).

        Args:
            date_obj: datetime object

        Returns:
            Date string in YYYY-MM-DD format, or empty string if None

        Examples:
            >>> from datetime import datetime
            >>> dt = datetime(2025, 12, 21, 11, 5)
            >>> DateFormatter.to_obsidian_date(dt)
            '2025-12-21'
        """
        if not date_obj:
            return ""

        return date_obj.strftime(DateFormatter.OBSIDIAN_DATE_FORMAT)

    @staticmethod
    def to_obsidian_datetime(date_obj: Optional[datetime]) -> str:
        """
        Format datetime to Obsidian datetime format (YYYY-MM-DD HH:MM).

        Args:
            date_obj: datetime object

        Returns:
            Datetime string in YYYY-MM-DD HH:MM format, or empty string if None

        Examples:
            >>> from datetime import datetime
            >>> dt = datetime(2025, 12, 21, 14, 30)
            >>> DateFormatter.to_obsidian_datetime(dt)
            '2025-12-21 14:30'
        """
        if not date_obj:
            return ""

        return date_obj.strftime(DateFormatter.OBSIDIAN_DATETIME_FORMAT)

    @staticmethod
    def parse_and_format_date(zotero_date_str: Optional[str]) -> str:
        """
        Parse Zotero date and format for Obsidian (date only).

        Args:
            zotero_date_str: Date string from Zotero API

        Returns:
            Formatted date string (YYYY-MM-DD) or empty string

        Examples:
            >>> DateFormatter.parse_and_format_date('2025-12-21T11:05:00Z')
            '2025-12-21'
        """
        date_obj = DateFormatter.parse_zotero_date(zotero_date_str)
        return DateFormatter.to_obsidian_date(date_obj)

    @staticmethod
    def parse_and_format_datetime(zotero_date_str: Optional[str]) -> str:
        """
        Parse Zotero date and format for Obsidian (with time).

        Args:
            zotero_date_str: Date string from Zotero API

        Returns:
            Formatted datetime string (YYYY-MM-DD HH:MM) or empty string

        Examples:
            >>> DateFormatter.parse_and_format_datetime('2025-12-21T11:05:00Z')
            '2025-12-21 11:05'
        """
        date_obj = DateFormatter.parse_zotero_date(zotero_date_str)
        return DateFormatter.to_obsidian_datetime(date_obj)

    @staticmethod
    def now_obsidian_datetime() -> str:
        """
        Get current datetime in Obsidian format.

        Returns:
            Current datetime as YYYY-MM-DD HH:MM

        Examples:
            >>> DateFormatter.now_obsidian_datetime()  # doctest: +SKIP
            '2025-12-21 14:30'
        """
        return datetime.now().strftime(DateFormatter.OBSIDIAN_DATETIME_FORMAT)

    @staticmethod
    def now_obsidian_date() -> str:
        """
        Get current date in Obsidian format.

        Returns:
            Current date as YYYY-MM-DD

        Examples:
            >>> DateFormatter.now_obsidian_date()  # doctest: +SKIP
            '2025-12-21'
        """
        return datetime.now().strftime(DateFormatter.OBSIDIAN_DATE_FORMAT)
