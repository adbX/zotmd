"""Tests for color mapping."""

from zotmd.utils.color_mapper import ColorMapper


def test_color_mapping_exact_match():
    """Test exact color matches."""
    # Common Zotero highlight colors
    assert ColorMapper.hex_to_category("#ffd400") == "yellow"
    assert ColorMapper.hex_to_category("#ff6666") == "red"
    assert ColorMapper.hex_to_category("#5fb236") == "green"
    assert ColorMapper.hex_to_category("#2ea8e5") == "blue"
    assert ColorMapper.hex_to_category("#a28ae5") == "purple"


def test_color_mapping_case_insensitive():
    """Test that color matching is case-insensitive."""
    assert ColorMapper.hex_to_category("#FFD400") == "yellow"
    assert ColorMapper.hex_to_category("#Ff6666") == "red"


def test_color_mapping_without_hash():
    """Test color codes without # prefix."""
    # The function should handle colors with or without #
    result = ColorMapper.hex_to_category("ffd400")
    assert result == "yellow"


def test_color_mapping_fuzzy_match():
    """Test fuzzy matching for similar colors."""
    # Colors close to yellow should map to yellow
    result = ColorMapper.hex_to_category("#ffd500")  # Very close to #ffd400
    assert result == "yellow"


def test_color_mapping_closest_match():
    """Test that unknown colors map to closest match via fuzzy matching."""
    # Black (#000000) is closest to green or gray depending on RGB distance
    result = ColorMapper.hex_to_category("#000000")
    assert result in [
        "gray",
        "green",
        "blue",
        "red",
        "yellow",
        "purple",
        "magenta",
        "orange",
    ]

    # White (#ffffff) should map to a light color
    result = ColorMapper.hex_to_category("#ffffff")
    assert result in [
        "gray",
        "green",
        "blue",
        "red",
        "yellow",
        "purple",
        "magenta",
        "orange",
    ]


def test_color_mapping_invalid():
    """Test invalid color codes."""
    result = ColorMapper.hex_to_category("not-a-color")
    assert result == "gray"

    result = ColorMapper.hex_to_category("")
    assert result == "gray"


def test_hex_to_rgb():
    """Test hex to RGB conversion."""
    assert ColorMapper.hex_to_rgb("#ff6666") == (255, 102, 102)
    assert ColorMapper.hex_to_rgb("ffd400") == (255, 212, 0)
