"""Tests for ZoteroItem model."""

import pytest

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


@pytest.mark.parametrize("title", [None, 42, ""])
def test_zotero_item_rejects_malformed_title(sample_zotero_item, title):
    sample_zotero_item["data"]["title"] = title

    assert ZoteroItem.from_api_response(sample_zotero_item, "1234567") is None


def test_zotero_item_normalizes_all_title_line_breaks(sample_zotero_item):
    sample_zotero_item["data"]["title"] = "First\r\nSecond\u2028Third"

    item = ZoteroItem.from_api_response(sample_zotero_item, "1234567")

    assert item is not None
    assert item.title == "First Second Third"


def test_zotero_item_keeps_only_manual_tags_and_parses_type_specific_venue(
    sample_zotero_item,
):
    data = sample_zotero_item["data"]
    data["publicationTitle"] = ""
    data["proceedingsTitle"] = "Proceedings of Exact Rendering"
    data["tags"] = [
        {"tag": "manual", "type": 0},
        {"tag": "/reading"},
        {"tag": "automatic", "type": 1},
    ]

    item = ZoteroItem.from_api_response(sample_zotero_item, library_id="1234567")

    assert item is not None
    assert item.tags == ["manual", "/reading"]
    assert item.venue == "Proceedings of Exact Rendering"
