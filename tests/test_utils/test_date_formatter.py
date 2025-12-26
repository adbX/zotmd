"""Tests for date formatting."""

from datetime import datetime

from zotmd.utils.date_formatter import DateFormatter


def test_parse_zotero_date():
    """Test parsing Zotero ISO 8601 dates."""
    result = DateFormatter.parse_zotero_date("2024-01-15T14:30:00Z")
    assert isinstance(result, datetime)
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15


def test_parse_zotero_date_invalid():
    """Test parsing invalid dates."""
    assert DateFormatter.parse_zotero_date("not-a-date") is None
    assert DateFormatter.parse_zotero_date("") is None
    assert DateFormatter.parse_zotero_date(None) is None


def test_to_obsidian_date():
    """Test formatting datetime to Obsidian date."""
    dt = datetime(2024, 1, 15, 14, 30)
    result = DateFormatter.to_obsidian_date(dt)
    assert result == "2024-01-15"


def test_to_obsidian_datetime():
    """Test formatting datetime to Obsidian datetime."""
    dt = datetime(2024, 1, 15, 14, 30)
    result = DateFormatter.to_obsidian_datetime(dt)
    assert result == "2024-01-15 14:30"


def test_parse_and_format_date():
    """Test parsing and formatting in one step."""
    result = DateFormatter.parse_and_format_date("2024-01-15T14:30:00Z")
    assert result == "2024-01-15"


def test_parse_and_format_datetime():
    """Test parsing and formatting datetime."""
    result = DateFormatter.parse_and_format_datetime("2024-01-15T14:30:00Z")
    assert result == "2024-01-15 14:30"


def test_now_obsidian_date():
    """Test getting current date."""
    result = DateFormatter.now_obsidian_date()
    assert len(result) == 10  # YYYY-MM-DD format
    assert "-" in result


def test_now_obsidian_datetime():
    """Test getting current datetime."""
    result = DateFormatter.now_obsidian_datetime()
    assert len(result) == 16  # YYYY-MM-DD HH:MM format
    assert " " in result
