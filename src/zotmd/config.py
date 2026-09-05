"""Configuration management for zotmd."""

import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w
from platformdirs import user_config_dir, user_data_dir

APP_NAME = "zotmd"
API_KEY_ENV_VAR = "ZOTMD_API_KEY"

_SCHEMA = {
    "zotero": frozenset({"library_id", "api_key"}),
    "sync": frozenset({"output_dir", "deletion_behavior"}),
    "advanced": frozenset({"db_path", "template_path"}),
}


class ConfigDurabilityError(RuntimeError):
    """Raised when a replaced configuration may not be crash-durable."""


@dataclass
class Config:
    """Configuration for zotmd."""

    library_id: str
    api_key: str = field(repr=False)
    output_dir: Path
    deletion_behavior: str
    db_path: Path | None = None
    template_path: Path | None = None
    stored_api_key: str | None = field(default=None, repr=False, compare=False)
    persist_api_key: bool = field(default=True, repr=False, compare=False)

    def get_db_path(self) -> Path:
        """Get the database path, using the platform default if not set."""
        if self.db_path is not None:
            return self.db_path
        return get_default_db_path()

    def get_template_path(self) -> Path | None:
        """Get the template path, or None for the built-in template."""
        return self.template_path


def get_config_dir() -> Path:
    """Get the platform-specific configuration directory path."""
    return Path(user_config_dir(APP_NAME))


def get_data_dir() -> Path:
    """Get the platform-specific data directory path."""
    return Path(user_data_dir(APP_NAME))


def get_config_path() -> Path:
    """Get the full path to the config file."""
    return get_config_dir() / "config.toml"


def get_default_db_path() -> Path:
    """Get the default SQLite database path."""
    return get_data_dir() / "sync.sqlite"


def config_exists() -> bool:
    """Check whether the configuration file exists."""
    return get_config_path().exists()


def _validate_schema(data: dict[str, object]) -> None:
    unknown_sections = data.keys() - _SCHEMA.keys()
    if unknown_sections:
        names = ", ".join(sorted(unknown_sections))
        raise ValueError(f"Unknown config section(s): {names}")

    for section_name, allowed_keys in _SCHEMA.items():
        section = data.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ValueError(f"Config section [{section_name}] must be a table")

        unknown_keys = section.keys() - allowed_keys
        if unknown_keys:
            names = ", ".join(f"{section_name}.{key}" for key in sorted(unknown_keys))
            raise ValueError(f"Unknown config key(s): {names}")


def _get_section(data: dict[str, object], name: str) -> dict[str, object]:
    section = data.get(name)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"Config section [{name}] must be a table")
    return section


def _get_string(
    section: dict[str, object],
    section_name: str,
    key: str,
    *,
    required: bool = False,
) -> str | None:
    qualified_name = f"{section_name}.{key}"
    if key not in section:
        if required:
            raise ValueError(f"Missing {qualified_name} in config")
        return None

    value = section[key]
    if not isinstance(value, str):
        raise ValueError(f"{qualified_name} must be a string")
    if required and not value.strip():
        raise ValueError(f"{qualified_name} must not be blank")
    return value


def _resolve_path(value: str, config_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    return path.resolve()


def load_config() -> Config:
    """Load and validate configuration from the platform config file."""
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration not found at {config_path}. Run 'zotmd config' first."
        )

    with config_path.open("rb") as config_file:
        data: dict[str, object] = tomllib.load(config_file)

    _validate_schema(data)
    zotero = _get_section(data, "zotero")
    sync = _get_section(data, "sync")
    advanced = _get_section(data, "advanced")

    library_id = _get_string(zotero, "zotero", "library_id", required=True)
    assert library_id is not None
    stored_api_key = _get_string(zotero, "zotero", "api_key")
    environment_api_key = os.environ.get(API_KEY_ENV_VAR)
    if environment_api_key is not None and environment_api_key.strip():
        api_key = environment_api_key
    elif stored_api_key is None:
        raise ValueError(f"Missing zotero.api_key in config or {API_KEY_ENV_VAR}")
    elif not stored_api_key.strip():
        raise ValueError("zotero.api_key must not be blank")
    else:
        api_key = stored_api_key

    output_dir_string = _get_string(sync, "sync", "output_dir", required=True)
    deletion_behavior = _get_string(sync, "sync", "deletion_behavior", required=True)
    assert output_dir_string is not None
    assert deletion_behavior is not None
    if deletion_behavior not in {"move", "delete"}:
        raise ValueError("sync.deletion_behavior must be 'move' or 'delete'")

    db_path_string = _get_string(advanced, "advanced", "db_path")
    template_path_string = _get_string(advanced, "advanced", "template_path")
    config_dir = config_path.parent.resolve()
    output_dir = _resolve_path(output_dir_string, config_dir)
    db_path = (
        _resolve_path(db_path_string, config_dir)
        if db_path_string and db_path_string.strip()
        else None
    )
    template_path = (
        _resolve_path(template_path_string, config_dir)
        if template_path_string and template_path_string.strip()
        else None
    )
    if template_path is not None and not template_path.is_file():
        raise ValueError(f"advanced.template_path is not a file: {template_path}")

    return Config(
        library_id=library_id,
        api_key=api_key,
        output_dir=output_dir,
        deletion_behavior=deletion_behavior,
        db_path=db_path,
        template_path=template_path,
        stored_api_key=stored_api_key,
        persist_api_key=stored_api_key is not None,
    )


def save_config(config: Config) -> None:
    """Serialize and atomically save configuration to the platform config file."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    zotero = {"library_id": config.library_id}
    if config.persist_api_key:
        zotero["api_key"] = (
            config.stored_api_key
            if config.stored_api_key is not None
            else config.api_key
        )

    data = {
        "zotero": zotero,
        "sync": {
            "output_dir": str(config.output_dir),
            "deletion_behavior": config.deletion_behavior,
        },
        "advanced": {
            "db_path": str(config.db_path) if config.db_path is not None else "",
            "template_path": (
                str(config.template_path) if config.template_path is not None else ""
            ),
        },
    }

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            tomli_w.dump(data, temporary_file)
            os.fchmod(temporary_file.fileno(), 0o600)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        temporary_path.replace(config_path)
        try:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            for directory in (config_path.parent, config_path.parent.parent):
                directory_fd = os.open(directory, directory_flags)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as error:
            raise ConfigDurabilityError(
                f"Configuration was replaced at {config_path}, but its crash "
                "durability could not be confirmed"
            ) from error
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def mask_api_key(api_key: str) -> str:
    """Mask an API key for display, showing first 3 and last 3 characters."""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:3]}...{api_key[-3:]}"
