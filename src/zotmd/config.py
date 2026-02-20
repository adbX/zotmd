"""Configuration management for zotero-md-sync."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir, user_data_dir


APP_NAME = "zotmd"


@dataclass
class Config:
    """Configuration for zotero-md-sync."""

    # Zotero credentials
    library_id: str
    api_key: str
    library_type: str  # "user" or "group"

    # Sync settings
    output_dir: Path
    deletion_behavior: str  # "move" or "delete"

    # Advanced (optional)
    db_path: Optional[Path] = None
    template_path: Optional[Path] = None

    def get_db_path(self) -> Path:
        """Get the database path, using default if not set."""
        if self.db_path:
            return self.db_path
        return get_default_db_path()

    def get_template_path(self) -> Optional[Path]:
        """Get the template path, or None for built-in template."""
        return self.template_path


def get_config_dir() -> Path:
    """Get the configuration directory path.

    Returns ~/.config/zotmd/ on Linux/macOS, %APPDATA%/zotmd/ on Windows.
    """
    return Path(user_config_dir(APP_NAME))


def get_data_dir() -> Path:
    """Get the data directory path.

    Returns ~/.local/share/zotmd/ on Linux/macOS, %LOCALAPPDATA%/zotmd/ on Windows.
    """
    return Path(user_data_dir(APP_NAME))


def get_config_path() -> Path:
    """Get the full path to the config file."""
    return get_config_dir() / "config.toml"


def get_default_db_path() -> Path:
    """Get the default database path."""
    return get_data_dir() / "sync.sqlite"


def config_exists() -> bool:
    """Check if the configuration file exists."""
    return get_config_path().exists()


def load_config() -> Config:
    """Load configuration from TOML file.

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    config_path = get_config_path()

    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration not found at {config_path}. Run 'zotmd config' first."
        )

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    try:
        zotero = data.get("zotero", {})
        sync = data.get("sync", {})
        advanced = data.get("advanced", {})

        # Parse required fields
        library_id = zotero.get("library_id")
        api_key = zotero.get("api_key")
        library_type = zotero.get("library_type", "user")
        output_dir = sync.get("output_dir")
        deletion_behavior = sync.get("deletion_behavior", "move")

        if not library_id:
            raise ValueError("Missing zotero.library_id in config")
        if not api_key:
            raise ValueError("Missing zotero.api_key in config")
        if not output_dir:
            raise ValueError("Missing sync.output_dir in config")

        # Parse optional fields
        db_path_str = advanced.get("db_path", "")
        template_path_str = advanced.get("template_path", "")

        db_path = Path(db_path_str) if db_path_str else None
        template_path = Path(template_path_str) if template_path_str else None

        return Config(
            library_id=str(library_id),
            api_key=str(api_key),
            library_type=library_type,
            output_dir=Path(output_dir).expanduser(),
            deletion_behavior=deletion_behavior,
            db_path=db_path.expanduser() if db_path else None,
            template_path=template_path.expanduser() if template_path else None,
        )

    except KeyError as e:
        raise ValueError(f"Invalid config file: missing key {e}")


def save_config(config: Config) -> None:
    """Save configuration to TOML file.

    Creates the config directory if it doesn't exist.
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = get_config_path()

    # Format TOML manually (no built-in TOML writer in Python)
    lines = [
        "[zotero]",
        f'library_id = "{config.library_id}"',
        f'api_key = "{config.api_key}"',
        f'library_type = "{config.library_type}"',
        "",
        "[sync]",
        f'output_dir = "{config.output_dir}"',
        f'deletion_behavior = "{config.deletion_behavior}"',
        "",
        "[advanced]",
        f'db_path = "{config.db_path or ""}"',
        f'template_path = "{config.template_path or ""}"',
        "",
    ]

    config_path.write_text("\n".join(lines))


def mask_api_key(api_key: str) -> str:
    """Mask an API key for display, showing first 3 and last 3 characters."""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:3]}...{api_key[-3:]}"
