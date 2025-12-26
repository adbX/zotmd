"""Tests for Annotation model."""

from zotmd.models.annotation import Annotation


def test_annotation_from_api(sample_annotation):
    """Test creating Annotation from API response."""
    annotation = Annotation.from_api_response(sample_annotation)

    assert annotation.key == "ANNOT123"
    assert annotation.parent_key == "ABC123XYZ"  # Changed from parent_item
    assert annotation.annotation_type == "highlight"
    assert annotation.text == "This is the highlighted text from the PDF."
    assert annotation.comment == "This is my note about the highlight."
    assert annotation.color_hex == "#ff6666"  # Changed from color
    assert annotation.page_label == "5"


def test_annotation_properties(sample_annotation):
    """Test annotation properties."""
    annotation = Annotation.from_api_response(sample_annotation)

    # Check that the annotation is a dataclass
    assert hasattr(annotation, "key")
    assert hasattr(annotation, "parent_key")
    assert hasattr(annotation, "color_category")
    assert annotation.color_category == "red"  # #ff6666 maps to red


def test_annotation_without_comment(sample_annotation):
    """Test annotation without comment."""
    sample_annotation["data"]["annotationComment"] = ""
    annotation = Annotation.from_api_response(sample_annotation)

    assert annotation.comment == "" or annotation.comment is None


def test_annotation_without_page_label(sample_annotation):
    """Test annotation without page label."""
    sample_annotation["data"]["annotationPageLabel"] = ""
    annotation = Annotation.from_api_response(sample_annotation)

    assert annotation.page_label == "" or annotation.page_label is None
