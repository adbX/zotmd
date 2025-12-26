"""Shared test fixtures for zotmd."""

import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config_dict() -> dict[str, Any]:
    """Sample configuration dictionary."""
    return {
        "zotero": {
            "library_id": "1234567",
            "api_key": "test_api_key_abc123xyz",
            "library_type": "user",
        },
        "sync": {
            "output_dir": "/tmp/test_references",
            "deletion_behavior": "move",
        },
        "advanced": {
            "db_path": "",
            "template_path": "",
        },
    }


@pytest.fixture
def sample_zotero_item() -> dict[str, Any]:
    """Sample Zotero API item response."""
    return {
        "key": "ABC123XYZ",
        "version": 42,
        "library": {"type": "user", "id": 1234567},
        "data": {
            "key": "ABC123XYZ",
            "version": 42,
            "itemType": "journalArticle",
            "title": "Sample Article Title",
            "creators": [
                {
                    "creatorType": "author",
                    "firstName": "John",
                    "lastName": "Doe",
                }
            ],
            "abstractNote": "This is a sample abstract.",
            "publicationTitle": "Journal of Testing",
            "volume": "10",
            "issue": "2",
            "pages": "123-145",
            "date": "2024-01-15",
            "DOI": "10.1234/test.2024.01",
            "url": "https://example.com/article",
            "extra": "Citation Key: doe2024sample",
            "tags": [
                {"tag": "testing"},
                {"tag": "sample"},
            ],
            "dateAdded": "2024-01-01T12:00:00Z",
            "dateModified": "2024-01-15T14:30:00Z",
        },
    }


@pytest.fixture
def sample_annotation() -> dict[str, Any]:
    """Sample Zotero annotation response."""
    return {
        "key": "ANNOT123",
        "version": 10,
        "library": {"type": "user", "id": 1234567},
        "data": {
            "key": "ANNOT123",
            "version": 10,
            "itemType": "annotation",
            "parentItem": "ABC123XYZ",
            "annotationType": "highlight",
            "annotationText": "This is the highlighted text from the PDF.",
            "annotationComment": "This is my note about the highlight.",
            "annotationColor": "#ff6666",
            "annotationPageLabel": "5",
            "annotationSortIndex": "00001|002345|00678",
            "dateAdded": "2024-01-15T15:00:00Z",
            "dateModified": "2024-01-15T15:05:00Z",
        },
    }


@pytest.fixture
def sample_zotero_item_no_citation_key() -> dict[str, Any]:
    """Sample Zotero item without a citation key (should be skipped)."""
    return {
        "key": "NOCITE123",
        "version": 5,
        "library": {"type": "user", "id": 1234567},
        "data": {
            "key": "NOCITE123",
            "version": 5,
            "itemType": "journalArticle",
            "title": "Article Without Citation Key",
            "creators": [
                {
                    "creatorType": "author",
                    "firstName": "Jane",
                    "lastName": "Smith",
                }
            ],
            "extra": "",  # No citation key
            "dateAdded": "2024-01-01T12:00:00Z",
            "dateModified": "2024-01-02T10:00:00Z",
        },
    }
