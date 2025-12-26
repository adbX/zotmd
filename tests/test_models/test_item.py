"""Tests for ZoteroItem model."""

from zotmd.models.item import ZoteroItem


def test_zotero_item_from_api(sample_zotero_item):
    """Test creating ZoteroItem from API response."""
    item = ZoteroItem.from_api_response(sample_zotero_item, library_id="1234567")

    assert item.key == "ABC123XYZ"
    assert item.version == 42
    assert item.item_type == "journalArticle"
    assert item.title == "Sample Article Title"
    assert item.citation_key == "doe2024sample"
    assert len(item.creators) == 1
    assert item.creators[0]["lastName"] == "Doe"
    assert item.publication_title == "Journal of Testing"  # Changed from publication
    assert item.doi == "10.1234/test.2024.01"
    assert len(item.tags) == 2


def test_zotero_item_missing_citation_key(sample_zotero_item_no_citation_key):
    """Test that items without citation keys return None."""
    item = ZoteroItem.from_api_response(
        sample_zotero_item_no_citation_key, library_id="1234567"
    )
    assert item is None


def test_zotero_item_properties(sample_zotero_item):
    """Test ZoteroItem properties."""
    item = ZoteroItem.from_api_response(sample_zotero_item, library_id="1234567")

    # Check that it's a proper dataclass
    assert hasattr(item, "key")
    assert hasattr(item, "citation_key")
    assert hasattr(item, "title")
    assert item.key == "ABC123XYZ"
    assert item.citation_key == "doe2024sample"
    assert item.title == "Sample Article Title"
