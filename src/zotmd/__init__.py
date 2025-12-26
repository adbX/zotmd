"""Zotero to Markdown synchronization tool."""

__version__ = "0.1.0"

from .config import Config, load_config, save_config, config_exists
from .core import StateManager, ZoteroClient, SyncEngine
from .models import ZoteroItem, Annotation
from .templates import TemplateRenderer
from .file_ops import FileManager

__all__ = [
    "Config",
    "load_config",
    "save_config",
    "config_exists",
    "StateManager",
    "ZoteroClient",
    "SyncEngine",
    "ZoteroItem",
    "Annotation",
    "TemplateRenderer",
    "FileManager",
]
