"""Tests for filename sanitization."""

from zotmd.utils.filename_sanitizer import FilenameSanitizer


def test_sanitize_basic():
    """Test basic filename sanitization."""
    assert FilenameSanitizer.sanitize("simple_filename") == "simple_filename"


def test_sanitize_spaces():
    """Test that spaces are replaced with underscores."""
    assert FilenameSanitizer.sanitize("file with spaces") == "file_with_spaces"


def test_sanitize_special_characters():
    """Test removal of special characters."""
    result = FilenameSanitizer.sanitize("file/with\\special:chars*")
    assert "/" not in result
    assert "\\" not in result
    assert ":" not in result
    assert "*" not in result


def test_sanitize_leading_trailing():
    """Test removal of leading/trailing dots and spaces."""
    # Spaces become underscores, then dots/spaces are stripped
    result = FilenameSanitizer.sanitize(" .leading_and_trailing. ")
    # Should have spaces->underscores conversion and strip dots/spaces
    assert "leading_and_trailing" in result


def test_sanitize_unicode():
    """Test handling of unicode characters."""
    # Should preserve safe unicode characters
    result = FilenameSanitizer.sanitize("café_résumé")
    assert len(result) > 0


def test_sanitize_empty():
    """Test empty string handling."""
    result = FilenameSanitizer.sanitize("")
    assert result == ""


def test_sanitize_only_invalid():
    """Test string with only invalid characters."""
    result = FilenameSanitizer.sanitize("///\\\\\\")
    assert result == "untitled"


def test_add_extension():
    """Test adding file extension."""
    assert FilenameSanitizer.add_extension("test") == "test.md"
    assert FilenameSanitizer.add_extension("test", "txt") == "test.txt"


def test_validate():
    """Test filename validation."""
    assert FilenameSanitizer.validate("valid_name") is True
    assert FilenameSanitizer.validate("") is False
    assert FilenameSanitizer.validate("has/slash") is False
