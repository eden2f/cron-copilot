"""Configuration loader with YAML support and file-watching.

Loads configuration from a YAML file, merges it with defaults,
and optionally watches the file for live changes via *watchdog*.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, fields
from pathlib import Path
from threading import Event
from typing import Any, Callable

import yaml
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from pycronguard.config.schema import (
    AlertConfig,
    AlertEmailConfig,
    AppConfig,
    LogConfig,
    RecoveryConfig,
    SchedulerConfig,
    ScriptConfig,
    StorageConfig,
    default_config,
    validate_config,
)

logger = logging.getLogger(__name__)

# Mapping from top-level key → dataclass type for nested conversion.
_SECTION_CLS: dict[str, type] = {
    "scheduler": SchedulerConfig,
    "storage": StorageConfig,
    "log": LogConfig,
    "alert": AlertConfig,
    "recovery": RecoveryConfig,
    "script": ScriptConfig,
}

_NESTED_CLS: dict[str, dict[str, type]] = {
    "alert": {"email": AlertEmailConfig},
}


def _expand_paths(config: AppConfig) -> AppConfig:
    """Expand ``~`` in all path-like string fields.

    Returns:
        AppConfig: The same config instance with paths expanded in-place.
    """
    config.storage.db_path = os.path.expanduser(config.storage.db_path)
    config.log.log_dir = os.path.expanduser(config.log.log_dir)
    config.script.script_dir = os.path.expanduser(config.script.script_dir)
    config.script.version_dir = os.path.expanduser(config.script.version_dir)
    config.pid_file = os.path.expanduser(config.pid_file)
    return config


class _ConfigFileHandler(FileSystemEventHandler):
    """Watchdog handler that fires *callback* when the config file changes."""

    def __init__(self, config_path: str, callback: Callable[[AppConfig], Any]) -> None:
        super().__init__()
        self._config_path = os.path.abspath(config_path)
        self._callback = callback

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if os.path.abspath(str(event.src_path)) == self._config_path:
            logger.info("Configuration file changed, reloading …")
            try:
                loader = ConfigLoader(self._config_path)
                new_config = loader.load()
                self._callback(new_config)
            except Exception:
                logger.exception("Failed to reload configuration")


class ConfigLoader:
    """Load, merge and validate application configuration.

    Parameters:
        config_path: Optional path to a YAML configuration file.
            If *None* or the file does not exist, defaults are used.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        self._observer: Observer | None = None
        self._stop_event = Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> AppConfig:
        """Load configuration from YAML and merge with defaults.

        Returns:
            AppConfig: Validated application configuration.
        """
        base = asdict(default_config())

        if self._config_path and Path(self._config_path).is_file():
            with open(self._config_path, "r", encoding="utf-8") as fh:
                override = yaml.safe_load(fh) or {}
            base = self._merge_dict(base, override)

        config = self._dict_to_config(base)
        config = _expand_paths(config)
        validate_config(config)
        return config

    def start_watch(self, callback: Callable[[AppConfig], Any]) -> None:
        """Watch the configuration file for changes.

        When the file is modified, *callback* is invoked with the newly
        loaded ``AppConfig``.

        Parameters:
            callback: Function called with the reloaded ``AppConfig``.
        """
        if not self._config_path:
            logger.warning("No config path set – cannot watch for changes")
            return

        self._stop_event.clear()
        handler = _ConfigFileHandler(self._config_path, callback)
        self._observer = Observer()
        self._observer.schedule(
            handler,
            path=str(Path(self._config_path).parent),
            recursive=False,
        )
        self._observer.daemon = True
        self._observer.start()
        logger.info("Started watching %s for changes", self._config_path)

    def stop_watch(self) -> None:
        """Stop watching the configuration file."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("Stopped configuration file watcher")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge *override* into *base*.

        Parameters:
            base: The base dictionary (defaults).
            override: Values that take precedence.

        Returns:
            dict: Merged dictionary.
        """
        merged = base.copy()
        for key, value in override.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = ConfigLoader._merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _dict_to_config(data: dict[str, Any]) -> AppConfig:
        """Convert a plain dictionary to a typed ``AppConfig`` instance.

        Parameters:
            data: Configuration dictionary.

        Returns:
            AppConfig: Typed configuration object.
        """
        kwargs: dict[str, Any] = {}
        app_fields = {f.name for f in fields(AppConfig)}

        for key, value in data.items():
            if key not in app_fields:
                continue
            if key in _SECTION_CLS and isinstance(value, dict):
                # Handle nested dataclasses inside sections (e.g. alert.email)
                nested_map = _NESTED_CLS.get(key, {})
                section_kwargs: dict[str, Any] = {}
                for sk, sv in value.items():
                    if sk in nested_map and isinstance(sv, dict):
                        section_kwargs[sk] = nested_map[sk](**sv)
                    else:
                        section_kwargs[sk] = sv
                kwargs[key] = _SECTION_CLS[key](**section_kwargs)
            else:
                kwargs[key] = value

        return AppConfig(**kwargs)
