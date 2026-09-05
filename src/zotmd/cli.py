"""Command-line interface for zotero-md-sync."""

import logging
import os
import sys
from pathlib import Path

import click

from .config import (
    API_KEY_ENV_VAR,
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
    prompt: str, default: str | None = None, password: bool = False
) -> str:
    """Prompt for input with an optional default value.

    If the user presses Enter without typing anything, the default is used.
    Returns empty string if no default and user enters nothing.
    """
    if password:
        label = f"{prompt} [default: {mask_api_key(default)}]" if default else prompt
        value = click.prompt(label, hide_input=True, default="", show_default=False)
    else:
        full_prompt = f"{prompt} [default: {default}]: " if default else f"{prompt}: "
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


def test_connection(library_id: str, api_key: str) -> tuple[bool, int | None]:
    """Test connection to Zotero API.

    Returns (success, library_version).
    """
    try:
        client = ZoteroClient(
            library_id=library_id,
            api_key=api_key,
        )
        version = client.get_library_version()
        return True, version
    except Exception:
        return False, None


def create_sync_engine(config: Config, *, dry_run: bool = False) -> SyncEngine:
    """Create and initialize sync engine from config."""
    renderer = TemplateRenderer(template_path=config.get_template_path())
    zotero_client = ZoteroClient(
        library_id=config.library_id,
        api_key=config.api_key,
    )

    db_path = config.get_db_path()
    state_manager = (
        StateManager(db_path=db_path, read_only=True)
        if dry_run and db_path.exists()
        else None
    )
    if not dry_run:
        state_manager = StateManager(
            db_path=db_path,
            library_id=config.library_id,
            output_root=config.output_dir,
        )
    try:
        file_manager = FileManager(
            base_dir=config.output_dir,
            deletion_behavior=config.deletion_behavior,
            create=False,
            read_only=dry_run,
        )
        return SyncEngine(
            zotero_client=zotero_client,
            state_manager=state_manager,
            renderer=renderer,
            file_manager=file_manager,
            library_id=config.library_id,
            dry_run=dry_run,
        )
    except BaseException:
        if state_manager is not None:
            state_manager.close()
        raise


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """ZotMD - Synchronize Zotero library to Markdown files.

    Export your Zotero items and PDF annotations as Obsidian-native Markdown.

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
    existing: Config | None = None
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

    environment_api_key = os.environ.get(API_KEY_ENV_VAR)
    if environment_api_key is not None and environment_api_key.strip():
        api_key = environment_api_key
        stored_api_key = existing.stored_api_key if existing else None
        persist_api_key = stored_api_key is not None
        click.echo(f"Using {API_KEY_ENV_VAR}; the environment key will not be stored.")
    else:
        api_key = prompt_with_default(
            "API Key",
            existing.stored_api_key if existing else None,
            password=True,
        )
        if not api_key:
            click.echo("Error: API Key is required.", err=True)
            sys.exit(1)
        stored_api_key = api_key
        persist_api_key = True

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
    if template_path is not None:
        template_to_validate = template_path
        if not template_to_validate.is_absolute():
            template_to_validate = get_config_path().parent / template_to_validate
        template_to_validate = template_to_validate.resolve()
        if not template_to_validate.is_file():
            click.echo(
                f"Error: Custom template is not a file: {template_to_validate}",
                err=True,
            )
            sys.exit(1)

    # Test connection
    click.echo("\nTesting connection to Zotero...")
    success, version = test_connection(library_id, api_key)

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
        output_dir=output_dir,
        deletion_behavior=deletion_behavior,
        db_path=db_path,
        template_path=template_path,
        stored_api_key=stored_api_key,
        persist_api_key=persist_api_key,
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
@click.option(
    "--dry-run",
    is_flag=True,
    help="Report changes without modifying state or files",
)
@click.option("--no-progress", is_flag=True, help="Disable progress bar")
@click.pass_context
def sync(ctx: click.Context, full: bool, dry_run: bool, no_progress: bool) -> None:
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

    engine: SyncEngine | None = None
    try:
        engine = create_sync_engine(config, dry_run=dry_run)
        if full:
            click.echo(
                "Planning full sync..." if dry_run else "Performing full sync..."
            )
            result = engine.full_sync(show_progress=not no_progress)
        else:
            click.echo(
                "Planning incremental sync..."
                if dry_run
                else "Performing incremental sync..."
            )
            result = engine.incremental_sync(show_progress=not no_progress)
    except Exception as e:
        click.echo(f"Error: Sync failed: {e}", err=True)
        if ctx.obj.get("verbose"):
            import traceback

            traceback.print_exc()
        sys.exit(1)
    finally:
        if engine is not None and engine.state is not None:
            engine.state.close()

    click.echo("\n" + "=" * 50)
    click.echo("Dry Run Complete" if dry_run else "Sync Complete")
    click.echo("=" * 50)
    click.echo(f"  Items processed: {result.total_items_processed}")
    click.echo(f"  Items created:   {result.items_created}")
    click.echo(f"  Items updated:   {result.items_updated}")
    click.echo(f"  Items renamed:   {result.items_renamed}")
    click.echo(f"  Items removed:   {result.items_removed}")
    click.echo(f"  Items deleted:   {result.items_deleted}")
    click.echo(f"  Output moves:    {result.output_items_moved}")
    click.echo(f"  Items skipped:   {result.items_skipped}")
    click.echo(f"  Annotations:     {result.annotations_synced}")
    click.echo(f"  Collisions:      {result.target_collisions}")

    if result.missing_citation_keys:
        click.echo(
            f"\nMissing citation keys ({len(result.missing_citation_keys)}): "
            + ", ".join(result.missing_citation_keys)
        )
    if result.errors:
        click.echo(f"\nErrors ({len(result.errors)}):", err=True)
        for error in result.errors[:5]:
            click.echo(f"  - {error}", err=True)
        if len(result.errors) > 5:
            click.echo(f"  ... and {len(result.errors) - 5} more", err=True)

    click.echo("=" * 50)
    if result.errors:
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
            click.echo("  Library Type: personal")
            click.echo(f"  Output Dir: {config.output_dir}")
            click.echo(f"  Deletion: {config.deletion_behavior}")
            click.echo(f"  Database: {config.get_db_path()}")
        except Exception as e:
            click.echo(f"  Error: Failed to read config: {e}", err=True)
            click.echo("=" * 50 + "\n")
            ctx.exit(1)
    else:
        click.echo("  Not configured. Run 'zotmd config' first.")
        click.echo("=" * 50 + "\n")
        ctx.exit(1)

    # Connection test
    failed = False
    click.echo("\nConnection:")
    success, version = test_connection(config.library_id, config.api_key)
    if success:
        click.echo("  Status: Connected")
        click.echo(f"  Library version: {version}")
    else:
        failed = True
        click.echo("  Status: Connection failed")
        click.echo("  Check credentials at: https://www.zotero.org/settings/keys")

    # Sync statistics
    db_path = config.get_db_path()
    if db_path.exists():
        click.echo("\nSync Statistics:")
        try:
            with StateManager(db_path=db_path, read_only=True) as state_manager:
                stats = state_manager.get_sync_stats()
            click.echo(f"  Active items: {stats['active_items']}")
            click.echo(f"  Removed items: {stats['removed_items']}")
            click.echo(f"  Total annotations: {stats['total_annotations']}")
            click.echo(f"  Last full sync: {stats['last_full_sync'] or 'Never'}")
            click.echo(
                f"  Last incr. sync: {stats['last_incremental_sync'] or 'Never'}"
            )
            click.echo(
                "  Library version: "
                + (
                    str(stats["last_library_version"])
                    if stats["last_library_version"] is not None
                    else "Unknown"
                )
            )
        except Exception as e:
            failed = True
            click.echo(f"  Error: Failed to read database: {e}", err=True)
    else:
        click.echo("\nSync Statistics:")
        click.echo("  No sync data yet. Run 'zotmd sync --full' first.")

    click.echo("=" * 50 + "\n")
    if failed:
        ctx.exit(1)


if __name__ == "__main__":
    main()
