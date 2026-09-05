"""Tests for CLI commands."""

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

import zotmd.cli as cli_module
from zotmd.cli import main
from zotmd.config import Config
from zotmd.core.state_manager import StateManager
from zotmd.core.sync_engine import SyncEngine, SyncResult
from zotmd.file_ops.file_manager import FileManager
from zotmd.templates.renderer import TemplateRenderer


def _configure_sync_command(monkeypatch, tmp_path, engine):
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=tmp_path,
        deletion_behavior="move",
    )
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr(cli_module, "config_exists", lambda: True)
    monkeypatch.setattr(cli_module, "load_config", lambda: config)
    monkeypatch.setattr(cli_module, "create_sync_engine", create_engine)
    return config, create_engine


def test_cli_help():
    """Test CLI help output."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "ZotMD" in result.output
    assert "Markdown" in result.output
    assert "init" in result.output
    assert "config" in result.output
    assert "sync" in result.output
    assert "status" in result.output


def test_status_without_config(monkeypatch):
    """Test status command when config doesn't exist."""
    import tempfile
    from pathlib import Path

    runner = CliRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir)
        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)

        result = runner.invoke(main, ["status"])

        assert result.exit_code == 1
        assert "not configured" in result.output.lower()


def test_status_connection_failure_returns_nonzero(monkeypatch, tmp_path):
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=tmp_path / "references",
        deletion_behavior="move",
        db_path=tmp_path / "missing.sqlite",
    )
    monkeypatch.setattr(cli_module, "config_exists", lambda: True)
    monkeypatch.setattr(cli_module, "load_config", lambda: config)
    monkeypatch.setattr(cli_module, "test_connection", lambda *args: (False, None))

    result = CliRunner().invoke(main, ["status"])

    assert result.exit_code == 1
    assert "Status: Connection failed" in result.output


def test_status_displays_completed_zero_library_version(monkeypatch, tmp_path):
    output = tmp_path / "references"
    db_path = tmp_path / "sync.sqlite"
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=output,
        deletion_behavior="move",
        db_path=db_path,
    )
    with StateManager(db_path, config.library_id, output) as state:
        state.update_library_version(0)
    monkeypatch.setattr(cli_module, "config_exists", lambda: True)
    monkeypatch.setattr(cli_module, "load_config", lambda: config)
    monkeypatch.setattr(cli_module, "test_connection", lambda *args: (True, 12))

    result = CliRunner().invoke(main, ["status"])

    assert result.exit_code == 0
    assert "Library version: 0" in result.output


def test_sync_without_config(monkeypatch):
    """Test sync command when config doesn't exist."""
    import tempfile
    from pathlib import Path

    runner = CliRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        fake_config_dir = Path(tmpdir)
        monkeypatch.setattr("zotmd.config.get_config_dir", lambda: fake_config_dir)

        result = runner.invoke(main, ["sync"])

        # Should exit with error about missing config
        assert result.exit_code != 0 or "not" in result.output.lower()


def test_sanitize_path():
    """Test filepath sanitization for whitespace and quotes."""
    from zotmd.cli import sanitize_path

    # Basic path - no changes
    assert sanitize_path("~/Documents/path") == "~/Documents/path"

    # Path with surrounding whitespace
    assert sanitize_path("  ~/Documents/path  ") == "~/Documents/path"

    # Path with double quotes
    assert sanitize_path('"~/Documents/path"') == "~/Documents/path"

    # Path with single quotes
    assert sanitize_path("'~/Documents/path'") == "~/Documents/path"

    # Path with quotes and whitespace
    assert sanitize_path('  "~/Documents/path"  ') == "~/Documents/path"

    # Path with spaces in the path itself (not surrounding)
    assert sanitize_path("~/Documents/my path") == "~/Documents/my path"

    # Quoted path with spaces in the name
    assert sanitize_path('"~/Documents/my path"') == "~/Documents/my path"

    # Whitespace inside quotes
    assert sanitize_path('"  ~/Documents/path  "') == "~/Documents/path"


@pytest.mark.parametrize(
    ("args", "selected_method", "other_method"),
    [
        (["sync", "--full", "--no-progress"], "full_sync", "incremental_sync"),
        (["sync", "--no-progress"], "incremental_sync", "full_sync"),
    ],
)
def test_sync_dispatches_to_requested_engine_method(
    monkeypatch, tmp_path, args, selected_method, other_method
):
    engine = MagicMock()
    expected = SyncResult(total_items_processed=2, items_created=1, items_updated=1)
    getattr(engine, selected_method).return_value = expected
    config, create_engine = _configure_sync_command(monkeypatch, tmp_path, engine)

    result = CliRunner().invoke(main, args)

    assert result.exit_code == 0
    create_engine.assert_called_once_with(config, dry_run=False)
    getattr(engine, selected_method).assert_called_once_with(show_progress=False)
    getattr(engine, other_method).assert_not_called()
    assert "Items processed: 2" in result.output


def test_sync_reports_engine_failure(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.incremental_sync.side_effect = RuntimeError("Zotero unavailable")
    _configure_sync_command(monkeypatch, tmp_path, engine)

    result = CliRunner().invoke(main, ["sync", "--no-progress"])

    assert result.exit_code == 1
    engine.incremental_sync.assert_called_once_with(show_progress=False)
    assert "Error: Sync failed: Zotero unavailable" in result.output


def test_sync_malformed_venue_returns_nonzero_without_mutation(monkeypatch, tmp_path):
    output = tmp_path / "references"
    db_path = tmp_path / "sync.sqlite"
    malformed = {
        "key": "ITEM-1",
        "version": 1,
        "data": {
            "key": "ITEM-1",
            "itemType": "conferencePaper",
            "title": "Malformed venue",
            "extra": "Citation Key: paper",
            "creators": [],
            "tags": [],
            "conferenceName": [],
        },
    }
    zotero = MagicMock()
    zotero.get_library_version.return_value = 1
    zotero.get_all_items.return_value = [malformed]
    zotero.get_all_annotations.return_value = []
    zotero.get_all_attachments.return_value = []
    state = StateManager(db_path, "1234567", output)
    before_checkpoint = state.get_checkpoint()
    engine = SyncEngine(
        zotero,
        state,
        TemplateRenderer(),
        FileManager(output, create=False),
        "1234567",
    )
    _configure_sync_command(monkeypatch, tmp_path, engine)

    result = CliRunner().invoke(main, ["sync", "--full", "--no-progress"])

    assert result.exit_code == 1
    assert "conferenceName is not a string" in result.output
    assert not output.exists()
    with StateManager(db_path, read_only=True) as stored_state:
        assert stored_state.get_active_items() == []
        assert stored_state.get_checkpoint() == before_checkpoint


def test_sync_prints_first_five_result_errors(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.incremental_sync.return_value = SyncResult(
        total_items_processed=6,
        errors=[f"item error {number}" for number in range(1, 7)],
    )
    _configure_sync_command(monkeypatch, tmp_path, engine)

    result = CliRunner().invoke(main, ["sync", "--no-progress"])

    assert result.exit_code == 1
    engine.incremental_sync.assert_called_once_with(show_progress=False)
    assert "Errors (6):" in result.output
    for number in range(1, 6):
        assert f"  - item error {number}" in result.output
    assert "item error 6" not in result.output
    assert "... and 1 more" in result.output


def test_sync_dry_run_uses_dry_engine_and_closes_state(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.incremental_sync.return_value = SyncResult(
        dry_run=True,
        items_created=2,
        items_renamed=1,
    )
    config, create_engine = _configure_sync_command(monkeypatch, tmp_path, engine)

    result = CliRunner().invoke(main, ["sync", "--dry-run", "--no-progress"])

    assert result.exit_code == 0
    create_engine.assert_called_once_with(config, dry_run=True)
    engine.incremental_sync.assert_called_once_with(show_progress=False)
    engine.state.close.assert_called_once_with()
    assert "Dry Run Complete" in result.output
    assert "Items created:   2" in result.output
    assert "Items renamed:   1" in result.output


def test_sync_closes_state_after_engine_failure(monkeypatch, tmp_path):
    engine = MagicMock()
    engine.incremental_sync.side_effect = RuntimeError("Zotero unavailable")
    _configure_sync_command(monkeypatch, tmp_path, engine)

    result = CliRunner().invoke(main, ["sync", "--no-progress"])

    assert result.exit_code == 1
    engine.state.close.assert_called_once_with()


def test_prompt_with_default_hides_password_input(monkeypatch):
    prompt = MagicMock(return_value="replacement")
    monkeypatch.setattr(cli_module.click, "prompt", prompt)

    value = cli_module.prompt_with_default("API Key", "stored-secret", password=True)

    assert value == "replacement"
    prompt.assert_called_once_with(
        "API Key [default: sto...ret]",
        hide_input=True,
        default="",
        show_default=False,
    )


def test_create_sync_engine_dry_run_without_state_creates_nothing(
    monkeypatch, tmp_path
):
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=tmp_path / "references",
        deletion_behavior="move",
        db_path=tmp_path / "state" / "sync.sqlite",
    )
    zotero = MagicMock()
    monkeypatch.setattr(cli_module, "ZoteroClient", MagicMock(return_value=zotero))

    engine = cli_module.create_sync_engine(config, dry_run=True)

    assert engine.state is None
    assert engine.dry_run is True
    assert engine.files.read_only is True
    assert not config.output_dir.exists()
    assert config.db_path is not None and not config.db_path.exists()


def test_create_sync_engine_defers_output_creation(monkeypatch, tmp_path):
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=tmp_path / "references",
        deletion_behavior="move",
        db_path=tmp_path / "state" / "sync.sqlite",
    )
    monkeypatch.setattr(cli_module, "ZoteroClient", MagicMock())

    engine = cli_module.create_sync_engine(config)
    try:
        assert engine.state is not None
        assert engine.files.read_only is False
        assert config.db_path is not None and config.db_path.is_file()
        assert not config.output_dir.exists()
    finally:
        assert engine.state is not None
        engine.state.close()


def test_create_sync_engine_closes_state_after_dependency_failure(
    monkeypatch, tmp_path
):
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=tmp_path / "references",
        deletion_behavior="invalid",
        db_path=tmp_path / "sync.sqlite",
    )
    state = MagicMock()
    monkeypatch.setattr(cli_module, "StateManager", MagicMock(return_value=state))
    monkeypatch.setattr(cli_module, "ZoteroClient", MagicMock())

    with pytest.raises(ValueError, match="deletion_behavior"):
        cli_module.create_sync_engine(config)

    state.close.assert_called_once_with()


def test_create_sync_engine_validates_template_before_creating_state(
    monkeypatch, tmp_path
):
    config = Config(
        library_id="1234567",
        api_key="secret",
        output_dir=tmp_path / "references",
        deletion_behavior="move",
        db_path=tmp_path / "state" / "sync.sqlite",
        template_path=tmp_path / "missing.md.j2",
    )
    zotero = MagicMock()
    monkeypatch.setattr(cli_module, "ZoteroClient", zotero)

    with pytest.raises(FileNotFoundError, match="Custom body template"):
        cli_module.create_sync_engine(config)

    zotero.assert_not_called()
    assert config.db_path is not None and not config.db_path.exists()


def test_init_does_not_persist_environment_api_key(monkeypatch, tmp_path):
    config = Config(
        library_id="1234567",
        api_key="environment-secret",
        output_dir=tmp_path / "references",
        deletion_behavior="move",
        stored_api_key=None,
        persist_api_key=False,
    )
    saved = MagicMock()
    prompts = iter(["1234567", str(config.output_dir), "move", "", ""])
    monkeypatch.setenv("ZOTMD_API_KEY", config.api_key)
    monkeypatch.setattr(cli_module, "config_exists", lambda: False)
    monkeypatch.setattr(
        cli_module, "prompt_with_default", lambda *args, **kwargs: next(prompts)
    )
    monkeypatch.setattr(cli_module, "test_connection", lambda *args: (True, 1))
    monkeypatch.setattr(cli_module, "save_config", saved)
    monkeypatch.setattr(
        cli_module, "get_default_db_path", lambda: tmp_path / "sync.sqlite"
    )
    monkeypatch.setattr(cli_module, "get_data_dir", lambda: tmp_path / "data")

    result = CliRunner().invoke(main, ["init"])

    assert result.exit_code == 0
    written = saved.call_args.args[0]
    assert written.api_key == "environment-secret"
    assert written.stored_api_key is None
    assert written.persist_api_key is False
    assert "environment key will not be stored" in result.output


def test_init_rejects_missing_custom_template_before_connection_or_write(
    monkeypatch, tmp_path
):
    missing_template = tmp_path / "templates" / "missing.md.j2"
    prompts = iter(
        [
            "1234567",
            "secret",
            str(tmp_path / "references"),
            "move",
            "",
            str(missing_template),
        ]
    )
    connection = MagicMock()
    save = MagicMock()
    monkeypatch.delenv("ZOTMD_API_KEY", raising=False)
    monkeypatch.setattr(cli_module, "config_exists", lambda: False)
    monkeypatch.setattr(
        cli_module, "prompt_with_default", lambda *args, **kwargs: next(prompts)
    )
    monkeypatch.setattr(cli_module, "test_connection", connection)
    monkeypatch.setattr(cli_module, "save_config", save)
    monkeypatch.setattr(
        cli_module, "get_default_db_path", lambda: tmp_path / "sync.sqlite"
    )

    result = CliRunner().invoke(main, ["init"])

    assert result.exit_code == 1
    assert f"Custom template is not a file: {missing_template}" in result.output
    connection.assert_not_called()
    save.assert_not_called()
