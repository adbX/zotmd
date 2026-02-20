"""Command-line interface for zotero-md-sync."""

import logging
import sys
from pathlib import Path
from typing import Optional

import click

from .config import (
    Config,
    config_exists,
    get_config_path,
    get_data_dir,
    get_default_db_path,
    load_config,
    mask_api_key,
    save_config,
)
from .core.state_manager import StateManager
from .core.sync_engine import SyncEngine
from .core.zotero_client import ZoteroClient
from .file_ops.file_manager import FileManager
from .templates.renderer import TemplateRenderer


def setup_logging(verbose: bool = False) -> None:
    """Configure console-only logging."""
    level = logging.DEBUG if verbose else logging.WARNING

    formatter = logging.Formatter("%(levelname)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = []
    root_logger.addHandler(console_handler)

    # Suppress noisy library loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pyzotero").setLevel(logging.WARNING)


def prompt_with_default(
    prompt: str, default: Optional[str] = None, password: bool = False
) -> str:
    """Prompt for input with an optional default value.

    If the user presses Enter without typing anything, the default is used.
    Returns empty string if no default and user enters nothing.
    """
    if default:
        if password:
            display_default = mask_api_key(default)
        else:
            display_default = default
        full_prompt = f"{prompt} [default: {display_default}]: "
    else:
        full_prompt = f"{prompt}: "

    if password and not default:
        # Use click.prompt for hidden input when no default
        value = click.prompt(prompt, hide_input=True, default="", show_default=False)
    else:
        value = input(full_prompt).strip()

    if not value and default:
        return default
    return value


def sanitize_path(path_str: str) -> str:
    """Sanitize a file path string by removing surrounding whitespace and quotes.

    Handles paths that may have been copied with surrounding quotes or have
    leading/trailing whitespace.
    """
    # Strip whitespace first
    path_str = path_str.strip()

    # Remove surrounding quotes (single or double)
    if (path_str.startswith('"') and path_str.endswith('"')) or (
        path_str.startswith("'") and path_str.endswith("'")
    ):
        path_str = path_str[1:-1]

    # Strip again in case there was whitespace inside the quotes
    return path_str.strip()


def test_connection(
    library_id: str, api_key: str, library_type: str
) -> tuple[bool, Optional[int]]:
    """Test connection to Zotero API.

    Returns (success, library_version).
    """
    try:
        client = ZoteroClient(
            library_id=library_id,
            library_type=library_type,
            api_key=api_key,
        )
        version = client.get_library_version()
        return True, version
    except Exception:
        return False, None


def create_sync_engine(config: Config) -> SyncEngine:
    """Create and initialize sync engine from config."""
    zotero_client = ZoteroClient(
        library_id=config.library_id,
        library_type=config.library_type,
        api_key=config.api_key,
    )

    state_manager = StateManager(db_path=config.get_db_path())
    renderer = TemplateRenderer(template_path=config.get_template_path())
    file_manager = FileManager(
        base_dir=config.output_dir,
        deletion_behavior=config.deletion_behavior,
    )

    return SyncEngine(
        zotero_client=zotero_client,
        state_manager=state_manager,
        renderer=renderer,
        file_manager=file_manager,
        library_id=config.library_id,
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """ZotMD - Synchronize Zotero library to Markdown files.

    Export your Zotero items and PDF annotations to Markdown for use
    with Obsidian, Logseq, or other note-taking apps.

    Get started with: zotmd config
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize or update configuration interactively.

    Prompts for Zotero API credentials, output directory, and sync settings.
    Press Enter to keep existing values when updating configuration.
    """
    click.echo("\nZotMD - Configuration")
    click.echo("=" * 35)

    # Load existing config if available
    existing: Optional[Config] = None
    if config_exists():
        try:
            existing = load_config()
            click.echo("(Press Enter to keep current value)\n")
        except Exception:
            click.echo("(Existing config is invalid, starting fresh)\n")

    # Show link to Zotero API key page
    click.echo("Get your Library ID and API Key at:")
    click.echo("  https://www.zotero.org/settings/keys\n")

    # Prompt for each setting
    library_id = prompt_with_default(
        "Library ID",
        existing.library_id if existing else None,
    )
    if not library_id:
        click.echo("Error: Library ID is required.", err=True)
        sys.exit(1)

    api_key = prompt_with_default(
        "API Key",
        existing.api_key if existing else None,
        password=True,
    )
    if not api_key:
        click.echo("Error: API Key is required.", err=True)
        sys.exit(1)

    library_type = prompt_with_default(
        "Library Type (user/group)",
        existing.library_type if existing else "user",
    )
    if library_type not in ("user", "group"):
        click.echo("Error: Library type must be 'user' or 'group'.", err=True)
        sys.exit(1)

    output_dir_str = prompt_with_default(
        "Output Directory",
        str(existing.output_dir) if existing else None,
    )
    if not output_dir_str:
        click.echo("Error: Output directory is required.", err=True)
        sys.exit(1)
    output_dir = Path(sanitize_path(output_dir_str)).expanduser()

    deletion_behavior = prompt_with_default(
        "Deletion Behavior (move/delete)",
        existing.deletion_behavior if existing else "move",
    )
    if deletion_behavior not in ("move", "delete"):
        click.echo("Error: Deletion behavior must be 'move' or 'delete'.", err=True)
        sys.exit(1)

    # Database path (optional)
    default_db = str(get_default_db_path())
    current_db = str(existing.db_path) if existing and existing.db_path else default_db
    db_path_str = prompt_with_default(
        "Database Path (Enter for default)",
        current_db,
    )
    db_path_str = sanitize_path(db_path_str)
    db_path = Path(db_path_str).expanduser() if db_path_str != default_db else None

    # Template path (optional)
    current_template = (
        str(existing.template_path) if existing and existing.template_path else ""
    )
    template_path_str = prompt_with_default(
        "Custom Template Path (Enter for built-in)",
        current_template if current_template else None,
    )
    template_path_str = sanitize_path(template_path_str) if template_path_str else ""
    template_path = Path(template_path_str).expanduser() if template_path_str else None

    # Test connection
    click.echo("\nTesting connection to Zotero...")
    success, version = test_connection(library_id, api_key, library_type)

    if success:
        click.echo(f"Connected successfully (library version {version})")
    else:
        click.echo("Error: Failed to connect to Zotero API.", err=True)
        click.echo("Check your Library ID and API Key at:")
        click.echo("  https://www.zotero.org/settings/keys")
        if not click.confirm("Save configuration anyway?"):
            sys.exit(1)

    # Create and save config
    config = Config(
        library_id=library_id,
        api_key=api_key,
        library_type=library_type,
        output_dir=output_dir,
        deletion_behavior=deletion_behavior,
        db_path=db_path,
        template_path=template_path,
    )

    save_config(config)

    # Ensure data directory exists
    get_data_dir().mkdir(parents=True, exist_ok=True)

    click.echo(f"\nConfiguration saved to {get_config_path()}")


# Add 'config' as an alias for 'init'
@main.command("config")
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """Configure ZotMD settings (alias for 'init').

    Prompts for Zotero API credentials, output directory, and sync settings.
    Press Enter to keep existing values when updating configuration.
    """
    ctx.invoke(init)


@main.command()
@click.option("--full", is_flag=True, help="Force full sync (re-import all items)")
@click.option("--no-progress", is_flag=True, help="Disable progress bar")
@click.pass_context
def sync(ctx: click.Context, full: bool, no_progress: bool) -> None:
    """Synchronize Zotero library to Markdown files.

    By default, performs an incremental sync (only changed items since last sync).
    Use --full to re-import all items from scratch.
    """
    if not config_exists():
        click.echo("Error: Not configured. Run 'zotmd config' first.", err=True)
        sys.exit(1)

    try:
        config = load_config()
    except Exception as e:
        click.echo(f"Error: Failed to load configuration: {e}", err=True)
        sys.exit(1)

    click.echo(f"Syncing to {config.output_dir}")

    engine = create_sync_engine(config)

    try:
        if full:
            click.echo("Performing full sync...")
            result = engine.full_sync(show_progress=not no_progress)
        else:
            click.echo("Performing incremental sync...")
            result = engine.incremental_sync(show_progress=not no_progress)

        # Display results
        click.echo("\n" + "=" * 50)
        click.echo("Sync Complete")
        click.echo("=" * 50)
        click.echo(f"  Items processed: {result.total_items_processed}")
        click.echo(f"  Items created:   {result.items_created}")
        click.echo(f"  Items updated:   {result.items_updated}")
        click.echo(f"  Items removed:   {result.items_removed}")
        click.echo(f"  Items skipped:   {result.items_skipped}")
        click.echo(f"  Annotations:     {result.annotations_synced}")

        if result.errors:
            click.echo(f"\nErrors ({len(result.errors)}):", err=True)
            for error in result.errors[:5]:
                click.echo(f"  - {error}", err=True)
            if len(result.errors) > 5:
                click.echo(f"  ... and {len(result.errors) - 5} more", err=True)

        click.echo("=" * 50)

    except Exception as e:
        click.echo(f"Error: Sync failed: {e}", err=True)
        if ctx.obj.get("verbose"):
            import traceback

            traceback.print_exc()
        sys.exit(1)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current configuration and sync status.

    Displays connection status, sync statistics, and configuration details.
    """
    click.echo("\n" + "=" * 50)
    click.echo("ZotMD Status")
    click.echo("=" * 50)

    # Configuration
    click.echo("\nConfiguration:")
    config_path = get_config_path()
    if config_exists():
        click.echo(f"  Config file: {config_path}")
        try:
            config = load_config()
            click.echo(f"  Library ID: {config.library_id}")
            click.echo(f"  Library Type: {config.library_type}")
            click.echo(f"  Output Dir: {config.output_dir}")
            click.echo(f"  Deletion: {config.deletion_behavior}")
            click.echo(f"  Database: {config.get_db_path()}")
        except Exception as e:
            click.echo(f"  Error: Failed to read config: {e}", err=True)
            click.echo("=" * 50 + "\n")
            return
    else:
        click.echo("  Not configured. Run 'zotmd config' first.")
        click.echo("=" * 50 + "\n")
        return

    # Connection test
    click.echo("\nConnection:")
    success, version = test_connection(
        config.library_id, config.api_key, config.library_type
    )
    if success:
        click.echo("  Status: Connected")
        click.echo(f"  Library version: {version}")
    else:
        click.echo("  Status: Connection failed")
        click.echo("  Check credentials at: https://www.zotero.org/settings/keys")

    # Sync statistics
    db_path = config.get_db_path()
    if db_path.exists():
        click.echo("\nSync Statistics:")
        try:
            state_manager = StateManager(db_path=db_path)
            stats = state_manager.get_sync_stats()
            click.echo(f"  Active items: {stats['active_items']}")
            click.echo(f"  Removed items: {stats['removed_items']}")
            click.echo(f"  Total annotations: {stats['total_annotations']}")
            click.echo(f"  Last full sync: {stats['last_full_sync'] or 'Never'}")
            click.echo(
                f"  Last incr. sync: {stats['last_incremental_sync'] or 'Never'}"
            )
            click.echo(
                f"  Library version: {stats['last_library_version'] or 'Unknown'}"
            )
        except Exception as e:
            click.echo(f"  Error: Failed to read database: {e}", err=True)
    else:
        click.echo("\nSync Statistics:")
        click.echo("  No sync data yet. Run 'zotmd sync --full' first.")

    click.echo("=" * 50 + "\n")


if __name__ == "__main__":
    main()
