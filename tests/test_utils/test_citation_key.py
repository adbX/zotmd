"""Tests for citation key extraction."""

from zotmd.utils.citation_key import CitationKeyExtractor


def test_extract_citation_key_basic():
    """Test basic citation key extraction."""
    item = {"data": {"extra": "Citation Key: doe2024sample"}}
    assert CitationKeyExtractor.extract(item) == "doe2024sample"


def test_extract_prefers_nonblank_native_citation_key():
    item = {
        "data": {
            "citationKey": " native2026 ",
            "extra": "Citation Key: fallback2026",
        }
    }

    assert CitationKeyExtractor.extract(item) == "native2026"


def test_extract_uses_extra_when_native_citation_key_is_blank():
    item = {
        "data": {
            "citationKey": "  ",
            "extra": "Citation Key: fallback2026",
        }
    }

    assert CitationKeyExtractor.extract(item) == "fallback2026"


def test_extract_citation_key_with_other_fields():
    """Test extraction when other fields are present."""
    item = {
        "data": {
            "extra": "Some other field\nCitation Key: smith2023test\nAnother field"
        }
    }
    assert CitationKeyExtractor.extract(item) == "smith2023test"


def test_extract_ignores_unanchored_citation_key_text():
    item = {"data": {"extra": "Comment: not a Citation Key: accidental"}}

    assert CitationKeyExtractor.extract(item) is None


def test_extract_citation_key_case_insensitive():
    """Test case-insensitive extraction."""
    item = {"data": {"extra": "citation key: lowercase2024"}}
    assert CitationKeyExtractor.extract(item) == "lowercase2024"


def test_extract_citation_key_with_whitespace():
    """Test extraction with extra whitespace."""
    item = {"data": {"extra": "  Citation Key:  whitespace2024  "}}
    assert CitationKeyExtractor.extract(item) == "whitespace2024"


def test_extract_citation_key_missing():
    """Test extraction when citation key is missing."""
    item = {"data": {"extra": "No citation key here"}}
    assert CitationKeyExtractor.extract(item) is None


def test_extract_citation_key_empty():
    """Test extraction with empty string."""
    item = {"data": {"extra": ""}}
    assert CitationKeyExtractor.extract(item) is None


def test_extract_citation_key_no_data():
    """Test extraction with missing data field."""
    item = {}
    assert CitationKeyExtractor.extract(item) is None


def test_extract_citation_key_special_characters():
    """Test extraction with special characters in key."""
    item = {"data": {"extra": "Citation Key: author2024_special-chars.v2"}}
    assert CitationKeyExtractor.extract(item) == "author2024_special-chars.v2"


def test_validate_citation_key():
    """Test citation key validation."""
    assert CitationKeyExtractor.validate("valid_key") is True
    assert CitationKeyExtractor.validate("doe2024") is True
    assert CitationKeyExtractor.validate("") is False
    assert CitationKeyExtractor.validate("has/slash") is False
    assert CitationKeyExtractor.validate("has:colon") is False
