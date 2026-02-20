"""Tests for configuration management."""

import tempfile
from pathlib import Path

import pytest
import tomli_w

from zotmd.config import (
    Config,
    config_exists,
    load_config,
    mask_api_key,
    save_config,
)


def test_mask_api_key():
    """Test API key masking."""
    assert mask_api_key("") == ""
    assert mask_api_key("abc") == "***"  # length <= 8 returns all stars
    assert mask_api_key("abcdefgh") == "********"  # length == 8
    assert mask_api_key("abcdefghi") == "abc...ghi"  # length > 8
    assert mask_api_key("abcdefghijk") == "abc...ijk"


def test_config_exists_false(monkeypatch):
    """Test config_exists returns False when config doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir)
        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)
        assert config_exists() is False


def test_config_exists_true(monkeypatch):
    """Test config_exists returns True when config exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir)
        config_file = fake_config_dir / "config.toml"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.touch()

        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)
        assert config_exists() is True


def test_save_and_load_config(monkeypatch, sample_config_dict):
    """Test saving and loading configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir)
        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)

        # Create config
        config = Config(
            library_id="1234567",
            api_key="test_api_key_abc123xyz",
            library_type="user",
            output_dir=Path("/tmp/test_references"),
            deletion_behavior="move",
        )

        # Save config
        save_config(config)

        # Verify file exists
        config_file = fake_config_dir / "config.toml"
        assert config_file.exists()

        # Load config
        loaded_config = load_config()

        # Verify values
        assert loaded_config.library_id == "1234567"
        assert loaded_config.api_key == "test_api_key_abc123xyz"
        assert loaded_config.library_type == "user"
        assert loaded_config.output_dir == Path("/tmp/test_references")
        assert loaded_config.deletion_behavior == "move"
        assert loaded_config.db_path is None
        assert loaded_config.template_path is None


def test_load_config_with_custom_paths(monkeypatch):
    """Test loading config with custom db_path and template_path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir)
        config_file = fake_config_dir / "config.toml"

        config_data = {
            "zotero": {
                "library_id": "9876543",
                "api_key": "custom_key",
                "library_type": "group",
            },
            "sync": {
                "output_dir": "/custom/path",
                "deletion_behavior": "delete",
            },
            "advanced": {
                "db_path": "/custom/db/sync.sqlite",
                "template_path": "/custom/template.md.j2",
            },
        }

        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "wb") as f:
            tomli_w.dump(config_data, f)

        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)

        loaded_config = load_config()

        assert loaded_config.library_id == "9876543"
        assert loaded_config.api_key == "custom_key"
        assert loaded_config.library_type == "group"
        assert loaded_config.output_dir == Path("/custom/path")
        assert loaded_config.deletion_behavior == "delete"
        assert loaded_config.db_path == Path("/custom/db/sync.sqlite")
        assert loaded_config.template_path == Path("/custom/template.md.j2")


def test_load_config_missing_file(monkeypatch):
    """Test loading config when file doesn't exist raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir)
        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)

        with pytest.raises(FileNotFoundError):
            load_config()


def test_save_config_creates_directory(monkeypatch):
    """Test that save_config creates the config directory if it doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir) / "new_subdir"
        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)

        config = Config(
            library_id="1234567",
            api_key="test_key",
            library_type="user",
            output_dir=Path("/tmp/refs"),
            deletion_behavior="move",
        )

        save_config(config)

        assert fake_config_dir.exists()
        assert (fake_config_dir / "config.toml").exists()
