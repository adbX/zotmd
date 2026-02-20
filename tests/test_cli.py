"""Tests for CLI commands."""

from click.testing import CliRunner

from zotmd.cli import main


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


def test_sanitize_path():
    """Test filepath sanitization for whitespace and quotes."""
    from zotmd.cli import sanitize_path

    # Basic path - no changes
    assert sanitize_path("/Users/test/path") == "/Users/test/path"

    # Path with surrounding whitespace
    assert sanitize_path("  /Users/test/path  ") == "/Users/test/path"

    # Path with double quotes
    assert sanitize_path('"/Users/test/path"') == "/Users/test/path"

    # Path with single quotes
    assert sanitize_path("'/Users/test/path'") == "/Users/test/path"

    # Path with quotes and whitespace
    assert sanitize_path('  "/Users/test/path"  ') == "/Users/test/path"

    # Path with spaces in the path itself (not surrounding)
    assert sanitize_path("/Users/test/my path") == "/Users/test/my path"

    # Quoted path with spaces in the name
    assert sanitize_path('"/Users/test/my path"') == "/Users/test/my path"

    # Whitespace inside quotes
    assert sanitize_path('"  /Users/test/path  "') == "/Users/test/path"
