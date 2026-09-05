"""Tests for configuration management."""

import stat
import tomllib
from pathlib import Path

import pytest
import tomli_w

import zotmd.config as config_module
from zotmd.config import (
    Config,
    config_exists,
    get_config_dir,
    get_config_path,
    get_data_dir,
    get_default_db_path,
    load_config,
    mask_api_key,
    save_config,
)


@pytest.fixture(autouse=True)
def clear_api_key_environment(monkeypatch):
    monkeypatch.delenv("ZOTMD_API_KEY", raising=False)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    monkeypatch.setattr(config_module, "get_config_dir", lambda: directory)
    return directory


def valid_config_data() -> dict:
    return {
        "zotero": {
            "library_id": "1234567",
            "api_key": "stored-key",
        },
        "sync": {
            "output_dir": "references",
            "deletion_behavior": "move",
        },
        "advanced": {},
    }


def write_config(config_dir: Path, data: dict) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    with config_path.open("wb") as config_file:
        tomli_w.dump(data, config_file)
    return config_path


def test_platformdirs_paths(monkeypatch):
    monkeypatch.setattr(config_module, "user_config_dir", lambda name: "/config/root")
    monkeypatch.setattr(config_module, "user_data_dir", lambda name: "/data/root")

    assert get_config_dir() == Path("/config/root")
    assert get_config_path() == Path("/config/root/config.toml")
    assert get_data_dir() == Path("/data/root")
    assert get_default_db_path() == Path("/data/root/sync.sqlite")


def test_config_exists(config_dir):
    assert config_exists() is False

    write_config(config_dir, valid_config_data())

    assert config_exists() is True


def test_load_config_missing_file(config_dir):
    with pytest.raises(FileNotFoundError, match="Configuration not found"):
        load_config()


def test_load_config_uses_default_paths(config_dir, tmp_path, monkeypatch):
    write_config(config_dir, valid_config_data())
    default_db_path = tmp_path / "data" / "sync.sqlite"
    monkeypatch.setattr(config_module, "get_default_db_path", lambda: default_db_path)

    config = load_config()

    assert config == Config(
        library_id="1234567",
        api_key="stored-key",
        output_dir=(config_dir / "references").resolve(),
        deletion_behavior="move",
    )
    assert config.get_db_path() == default_db_path
    assert config.get_template_path() is None


def test_load_config_resolves_relative_paths_from_config(config_dir):
    template_path = config_dir / "templates" / "note.md.j2"
    template_path.parent.mkdir(parents=True)
    template_path.write_text("{{ title }}", encoding="utf-8")
    data = valid_config_data()
    data["sync"]["output_dir"] = "notes/../references"
    data["advanced"] = {
        "db_path": "state/sync.sqlite",
        "template_path": "templates/note.md.j2",
    }
    write_config(config_dir, data)

    config = load_config()

    assert config.output_dir == (config_dir / "references").resolve()
    assert config.db_path == (config_dir / "state/sync.sqlite").resolve()
    assert config.template_path == template_path.resolve()
    assert config.output_dir.is_absolute()
    assert config.db_path is not None and config.db_path.is_absolute()
    assert config.template_path.is_absolute()


def test_load_config_expands_user_before_resolving(config_dir, tmp_path, monkeypatch):
    home = tmp_path / "home"
    template_path = home / "template.md.j2"
    home.mkdir()
    template_path.write_text("{{ title }}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    data = valid_config_data()
    data["sync"]["output_dir"] = "~/references"
    data["advanced"] = {
        "db_path": "~/state/sync.sqlite",
        "template_path": "~/template.md.j2",
    }
    write_config(config_dir, data)

    config = load_config()

    assert config.output_dir == (home / "references").resolve()
    assert config.db_path == (home / "state/sync.sqlite").resolve()
    assert config.template_path == template_path.resolve()


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("zotero", "library_type"),
        ("sync", "interval"),
        ("advanced", "debug"),
    ],
)
def test_load_config_rejects_unknown_keys(config_dir, section, key):
    data = valid_config_data()
    data[section][key] = "unexpected"
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=rf"Unknown config key.*{section}\.{key}"):
        load_config()


def test_load_config_rejects_unknown_section(config_dir):
    data = valid_config_data()
    data["logging"] = {"level": "debug"}
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=r"Unknown config section.*logging"):
        load_config()


@pytest.mark.parametrize("section", ["zotero", "sync", "advanced"])
def test_load_config_rejects_non_table_sections(config_dir, section):
    data = valid_config_data()
    data[section] = "not a table"
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=rf"section \[{section}\] must be a table"):
        load_config()


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("zotero", "library_id", 1234567),
        ("zotero", "api_key", True),
        ("sync", "output_dir", ["references"]),
        ("sync", "deletion_behavior", 1),
        ("advanced", "db_path", 1),
        ("advanced", "template_path", False),
    ],
)
def test_load_config_rejects_wrong_value_types(config_dir, section, key, value):
    data = valid_config_data()
    data[section][key] = value
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=rf"{section}\.{key} must be a string"):
        load_config()


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("zotero", "library_id"),
        ("zotero", "api_key"),
        ("sync", "output_dir"),
        ("sync", "deletion_behavior"),
    ],
)
def test_load_config_rejects_blank_required_values(config_dir, section, key):
    data = valid_config_data()
    data[section][key] = " \t "
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=rf"{section}\.{key}"):
        load_config()


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("zotero", "library_id"),
        ("sync", "output_dir"),
        ("sync", "deletion_behavior"),
    ],
)
def test_load_config_rejects_missing_required_values(config_dir, section, key):
    data = valid_config_data()
    del data[section][key]
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=rf"Missing {section}\.{key}"):
        load_config()


@pytest.mark.parametrize("behavior", ["archive", "Move", " move "])
def test_load_config_rejects_invalid_deletion_behavior(config_dir, behavior):
    data = valid_config_data()
    data["sync"]["deletion_behavior"] = behavior
    write_config(config_dir, data)

    with pytest.raises(
        ValueError, match=r"deletion_behavior must be 'move' or 'delete'"
    ):
        load_config()


def test_environment_api_key_overrides_stored_key(config_dir, monkeypatch):
    write_config(config_dir, valid_config_data())
    monkeypatch.setenv("ZOTMD_API_KEY", "environment-key")

    config = load_config()

    assert config.api_key == "environment-key"
    assert config.stored_api_key == "stored-key"
    assert config.persist_api_key is True


def test_environment_api_key_allows_missing_stored_key(config_dir, monkeypatch):
    data = valid_config_data()
    del data["zotero"]["api_key"]
    write_config(config_dir, data)
    monkeypatch.setenv("ZOTMD_API_KEY", "environment-key")

    config = load_config()

    assert config.api_key == "environment-key"
    assert config.stored_api_key is None
    assert config.persist_api_key is False


def test_save_config_does_not_persist_environment_key_over_blank_stored_key(
    config_dir, monkeypatch
):
    data = valid_config_data()
    data["zotero"]["api_key"] = ""
    write_config(config_dir, data)
    monkeypatch.setenv("ZOTMD_API_KEY", "environment-key")

    save_config(load_config())

    with (config_dir / "config.toml").open("rb") as config_file:
        saved = tomllib.load(config_file)
    assert saved["zotero"]["api_key"] == ""


def test_config_repr_does_not_expose_effective_or_stored_api_keys():
    config = Config(
        library_id="1234567",
        api_key="effective-secret",
        output_dir=Path("references"),
        deletion_behavior="move",
        stored_api_key="stored-secret",
    )

    representation = repr(config)

    assert "effective-secret" not in representation
    assert "stored-secret" not in representation
    assert "api_key" not in representation


@pytest.mark.parametrize("environment_key", ["", "   "])
def test_blank_environment_api_key_does_not_override_stored_key(
    config_dir, monkeypatch, environment_key
):
    write_config(config_dir, valid_config_data())
    monkeypatch.setenv("ZOTMD_API_KEY", environment_key)

    assert load_config().api_key == "stored-key"


def test_missing_api_key_without_environment_is_rejected(config_dir):
    data = valid_config_data()
    del data["zotero"]["api_key"]
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=r"Missing zotero\.api_key"):
        load_config()


@pytest.mark.parametrize("template_kind", ["missing", "directory"])
def test_load_config_rejects_non_file_template(config_dir, template_kind):
    template_path = config_dir / template_kind
    if template_kind == "directory":
        template_path.mkdir(parents=True)
    data = valid_config_data()
    data["advanced"] = {"template_path": template_kind}
    write_config(config_dir, data)

    with pytest.raises(ValueError, match=r"advanced\.template_path is not a file"):
        load_config()


def test_save_config_uses_toml_writer_for_sensitive_strings(config_dir):
    config = Config(
        library_id='id "quoted" \\ value\nnext',
        api_key='key "quoted" \\ value\nnext',
        output_dir=Path('references/"quoted"\\value'),
        deletion_behavior="delete",
        db_path=Path('state/"quoted"\\sync.sqlite'),
    )

    save_config(config)

    with (config_dir / "config.toml").open("rb") as config_file:
        data = tomllib.load(config_file)
    assert data == {
        "zotero": {
            "library_id": config.library_id,
            "api_key": config.api_key,
        },
        "sync": {
            "output_dir": str(config.output_dir),
            "deletion_behavior": "delete",
        },
        "advanced": {
            "db_path": str(config.db_path),
            "template_path": "",
        },
    }


def test_save_config_can_omit_environment_only_api_key(config_dir):
    config = Config(
        library_id="1234567",
        api_key="environment-secret",
        output_dir=Path("references"),
        deletion_behavior="move",
        persist_api_key=False,
    )

    save_config(config)

    with (config_dir / "config.toml").open("rb") as config_file:
        data = tomllib.load(config_file)
    assert data["zotero"] == {"library_id": "1234567"}


def test_save_config_creates_directory_and_sets_private_permissions(config_dir):
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=Path("references"),
        deletion_behavior="move",
    )

    save_config(config)

    config_path = config_dir / "config.toml"
    assert config_path.is_file()
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_save_config_atomically_replaces_existing_file(config_dir, monkeypatch):
    config_path = write_config(config_dir, valid_config_data())
    original_replace = Path.replace
    replacements = []

    def record_replace(source, target):
        replacements.append((source, Path(target)))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    save_config(
        Config(
            library_id="7654321",
            api_key="new-secret",
            output_dir=Path("new-references"),
            deletion_behavior="delete",
        )
    )

    assert len(replacements) == 1
    temporary_path, target_path = replacements[0]
    assert temporary_path.parent == config_path.parent
    assert temporary_path != config_path
    assert target_path == config_path
    with config_path.open("rb") as config_file:
        assert tomllib.load(config_file)["zotero"]["library_id"] == "7654321"


def test_save_config_preserves_existing_file_and_cleans_temp_on_failure(
    config_dir, monkeypatch
):
    config_path = write_config(config_dir, valid_config_data())
    original_contents = config_path.read_bytes()

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_config(
            Config(
                library_id="7654321",
                api_key="new-secret",
                output_dir=Path("new-references"),
                deletion_behavior="delete",
            )
        )

    assert config_path.read_bytes() == original_contents
    assert list(config_dir.glob(".config.toml.*.tmp")) == []


def test_save_config_reports_indeterminate_durability_after_replace(
    config_dir, monkeypatch
):
    config_path = write_config(config_dir, valid_config_data())
    original_fsync = config_module.os.fsync

    def fail_directory_fsync(descriptor):
        if stat.S_ISDIR(config_module.os.fstat(descriptor).st_mode):
            raise OSError("directory fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(config_module.os, "fsync", fail_directory_fsync)

    with pytest.raises(
        config_module.ConfigDurabilityError,
        match="Configuration was replaced.*durability could not be confirmed",
    ) as raised:
        save_config(
            Config(
                library_id="7654321",
                api_key="new-secret",
                output_dir=Path("new-references"),
                deletion_behavior="delete",
            )
        )

    assert str(raised.value.__cause__) == "directory fsync failed"
    with config_path.open("rb") as config_file:
        assert tomllib.load(config_file)["zotero"]["library_id"] == "7654321"
    assert list(config_dir.glob(".config.toml.*.tmp")) == []


def test_save_config_cleans_temp_when_serialization_fails(config_dir, monkeypatch):
    def fail_dump(data, file):
        file.write(b"partial")
        raise OSError("serialization failed")

    monkeypatch.setattr(config_module.tomli_w, "dump", fail_dump)
    with pytest.raises(OSError, match="serialization failed"):
        save_config(
            Config(
                library_id="1234567",
                api_key="secret",
                output_dir=Path("references"),
                deletion_behavior="move",
            )
        )

    assert not (config_dir / "config.toml").exists()
    assert list(config_dir.glob(".config.toml.*.tmp")) == []


def test_mask_api_key():
    assert mask_api_key("") == ""
    assert mask_api_key("abc") == "***"
    assert mask_api_key("abcdefgh") == "********"
    assert mask_api_key("abcdefghi") == "abc...ghi"
    assert mask_api_key("abcdefghijk") == "abc...ijk"
