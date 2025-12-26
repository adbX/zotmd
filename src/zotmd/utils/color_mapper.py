"""Map Zotero annotation hex colors to category names for markdown highlighting."""

import math


class ColorMapper:
    """Maps Zotero hex colors to human-readable category names."""

    # Standard Zotero annotation colors
    COLOR_MAP = {
        "#ffd400": "yellow",
        "#ff6666": "red",
        "#5fb236": "green",
        "#2ea8e5": "blue",
        "#a28ae5": "purple",
        "#e56eee": "magenta",
        "#f19837": "orange",
        "#aaaaaa": "gray",
    }

    @staticmethod
    def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """
        Convert hex color to RGB tuple.

        Args:
            hex_color: Hex color string (e.g., "#ff6666" or "ff6666")

        Returns:
            RGB tuple (r, g, b) with values 0-255

        Raises:
            ValueError: If hex_color is invalid
        """
        hex_color = hex_color.lstrip("#").lower()

        if len(hex_color) != 6:
            raise ValueError(f"Invalid hex color: #{hex_color}")

        try:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return (r, g, b)
        except ValueError as e:
            raise ValueError(f"Invalid hex color: #{hex_color}") from e

    @staticmethod
    def euclidean_distance(
        rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]
    ) -> float:
        """
        Calculate Euclidean distance between two RGB colors.

        Args:
            rgb1: First RGB tuple
            rgb2: Second RGB tuple

        Returns:
            Distance as float
        """
        return math.sqrt(
            (rgb1[0] - rgb2[0]) ** 2
            + (rgb1[1] - rgb2[1]) ** 2
            + (rgb1[2] - rgb2[2]) ** 2
        )

    @staticmethod
    def hex_to_category(hex_color: str) -> str:
        """
        Map hex color to category name with fuzzy matching fallback.

        Args:
            hex_color: Hex color string from Zotero annotation

        Returns:
            Category name (yellow, red, green, blue, purple, magenta, orange, gray)
            Defaults to "gray" if color cannot be matched

        Examples:
            >>> ColorMapper.hex_to_category("#a28ae5")
            'purple'

            >>> ColorMapper.hex_to_category("#ff6666")
            'red'

            >>> ColorMapper.hex_to_category("#a18ae4")  # Close to purple
            'purple'
        """
        if not hex_color:
            return "gray"

        # Normalize hex color
        hex_color = hex_color.strip().lower()
        if not hex_color.startswith("#"):
            hex_color = f"#{hex_color}"

        # Exact match
        if hex_color in ColorMapper.COLOR_MAP:
            return ColorMapper.COLOR_MAP[hex_color]

        # Fuzzy match using RGB distance
        try:
            target_rgb = ColorMapper.hex_to_rgb(hex_color)

            min_distance = float("inf")
            closest_category = "gray"

            for known_hex, category in ColorMapper.COLOR_MAP.items():
                known_rgb = ColorMapper.hex_to_rgb(known_hex)
                distance = ColorMapper.euclidean_distance(target_rgb, known_rgb)

                if distance < min_distance:
                    min_distance = distance
                    closest_category = category

            return closest_category

        except ValueError:
            # Invalid hex color, return default
            return "gray"

    @staticmethod
    def get_available_colors() -> dict[str, str]:
        """
        Get dictionary of all available color mappings.

        Returns:
            Dictionary mapping hex colors to category names
        """
        return ColorMapper.COLOR_MAP.copy()
