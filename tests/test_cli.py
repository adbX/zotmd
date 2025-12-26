"""Tests for CLI commands."""

from click.testing import CliRunner

from zotmd.cli import main


def test_cli_help():
    """Test CLI help output."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Zotero to Markdown" in result.output
    assert "init" in result.output
    assert "sync" in result.output
    assert "status" in result.output


def test_init_command_help():
    """Test init command help."""
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--help"])

    assert result.exit_code == 0
    assert "Initialize" in result.output


def test_sync_command_help():
    """Test sync command help."""
    runner = CliRunner()
    result = runner.invoke(main, ["sync", "--help"])

    assert result.exit_code == 0
    assert "Synchronize" in result.output
    assert "--full" in result.output
    assert "--no-progress" in result.output


def test_status_command_help():
    """Test status command help."""
    runner = CliRunner()
    result = runner.invoke(main, ["status", "--help"])

    assert result.exit_code == 0
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

        # Should exit with error or show "not initialized" message
        assert "not" in result.output.lower() or result.exit_code != 0


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
