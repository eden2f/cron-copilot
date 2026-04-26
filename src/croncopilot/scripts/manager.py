"""Script repository management.

Provides ``ScriptManager`` which acts as the central façade for script
registration, updates, validation, version history, and directory scanning.
"""

from __future__ import annotations

import os
import py_compile
import shutil
from typing import List, Optional, Tuple

from croncopilot.config.schema import ScriptConfig
from croncopilot.logging.logger import get_logger
from croncopilot.scripts.version import ScriptMetadata, VersionManager
from croncopilot.storage.database import DatabaseManager
from croncopilot.storage.models import ScriptMeta

logger = get_logger(__name__)


class ScriptManager:
    """High-level manager for the script repository.

    Handles script registration / un-registration, metadata updates,
    validation, directory scanning, and delegates version-control
    operations to ``VersionManager``.

    Parameters:
        config: ``ScriptConfig`` containing directory and version settings.
        db_manager: ``DatabaseManager`` for persistence.
    """

    def __init__(self, config: ScriptConfig, db_manager: DatabaseManager) -> None:
        self._config: ScriptConfig = config
        self._script_dir: str = os.path.expanduser(config.script_dir)
        self._db: DatabaseManager = db_manager
        self._version_mgr: VersionManager = VersionManager(
            version_dir=config.version_dir,
            max_versions=config.max_versions,
            db_manager=db_manager,
        )

        # Ensure the script directory exists.
        os.makedirs(self._script_dir, exist_ok=True)
        logger.debug("ScriptManager initialised (script_dir=%s)", self._script_dir)

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def _validate_script_path(self, script_path: str) -> str:
        """Validate that *script_path* resolves to a location inside ``script_dir``.

        This prevents path-traversal attacks where a crafted path (e.g.
        containing ``..``) could reference files outside the managed
        directory.

        Parameters:
            script_path: The path to validate (may be relative).

        Returns:
            The resolved absolute path.

        Raises:
            ValueError: If the resolved path falls outside ``script_dir``.
        """
        abs_path = os.path.abspath(script_path)
        abs_dir = os.path.abspath(self._script_dir)
        if not (abs_path.startswith(abs_dir + os.sep) or abs_path == abs_dir):
            raise ValueError(
                f"Script path '{script_path}' resolves outside the allowed "
                f"script directory '{abs_dir}'."
            )
        return abs_path

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        script_path: str,
        name: Optional[str] = None,
        author: str = "",
        description: str = "",
        category: str = "",
        venv_path: str = "",
    ) -> ScriptMetadata:
        """Register a script into the managed repository.

        If *script_path* is not already inside ``script_dir``, the file is
        copied there.  An initial version backup is created and metadata is
        persisted to the database.

        Parameters:
            script_path: Path to the script file.
            name: Unique name for the script.  Defaults to the filename
                without its extension.
            author: Author of the script.
            description: Human-readable description.
            category: Logical category / tag.
            venv_path: Path to a Python virtual-environment for this script.

        Returns:
            The ``ScriptMetadata`` for the newly registered script.

        Raises:
            FileNotFoundError: If *script_path* does not exist.
            ValueError: If a script with the same *name* is already registered.
        """
        script_path = os.path.expanduser(script_path)
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Script file not found: {script_path}")

        if name is None:
            name = os.path.splitext(os.path.basename(script_path))[0]

        # Check for duplicates.
        try:
            existing = self._db.get_script_meta(name)
        except Exception as exc:
            logger.error("Database error checking for existing script '%s': %s", name, exc)
            raise
        if existing is not None:
            raise ValueError(f"Script '{name}' is already registered.")

        # Copy into script_dir if necessary.
        abs_script = os.path.abspath(script_path)
        abs_dir = os.path.abspath(self._script_dir)
        if not abs_script.startswith(abs_dir + os.sep):
            dest = os.path.join(self._script_dir, os.path.basename(script_path))
            try:
                shutil.copy2(script_path, dest)
                logger.info("Copied script to managed directory: %s -> %s", script_path, dest)
            except OSError as exc:
                logger.error("Failed to copy script to script_dir: %s", exc)
                raise
            script_path = dest

        # Validate the final path is within the allowed directory.
        self._validate_script_path(script_path)

        # Compute hash.
        file_hash = self._version_mgr.compute_hash(script_path)

        # Build metadata.
        metadata = ScriptMetadata(
            name=name,
            path=script_path,
            author=author,
            description=description,
            category=category,
            venv_path=venv_path,
            file_hash=file_hash,
            version_count=0,
        )

        # Persist metadata first so backup can reference it.
        self._version_mgr.update_metadata(metadata)

        # Create initial version backup.
        try:
            self._version_mgr.backup_version(name, script_path)
        except (FileNotFoundError, OSError) as exc:
            logger.warning("Initial version backup failed for '%s': %s", name, exc)

        logger.info("Registered script '%s' at %s", name, script_path)
        return metadata

    def unregister(self, name: str, delete_file: bool = False) -> None:
        """Remove a script from the repository.

        Version backups are intentionally preserved for safety.

        Parameters:
            name: Registered script name.
            delete_file: If ``True``, also delete the script file from disk.
        """
        try:
            existing = self._db.get_script_meta(name)
        except Exception as exc:
            logger.error("Database error during unregister of '%s': %s", name, exc)
            raise

        if existing is None:
            logger.warning("Script '%s' not found; nothing to unregister.", name)
            return

        if delete_file and existing.path:
            file_path = os.path.expanduser(existing.path)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    logger.info("Deleted script file: %s", file_path)
                except OSError as exc:
                    logger.warning("Failed to delete script file %s: %s", file_path, exc)

        try:
            self._db.delete_script_meta(name)
        except Exception as exc:
            logger.error("Database error deleting metadata for '%s': %s", name, exc)
            raise

        logger.info("Unregistered script '%s' (delete_file=%s).", name, delete_file)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_script(self, name: str, new_path: Optional[str] = None, **metadata_kwargs: object) -> None:
        """Update a registered script and/or its metadata.

        If *new_path* is provided the old version is backed up (when
        changed) and the script file is replaced.

        Parameters:
            name: Registered script name.
            new_path: Optional new script file to replace the current one.
            **metadata_kwargs: Additional metadata fields to update (e.g.
                ``author``, ``description``, ``category``, ``venv_path``).

        Raises:
            ValueError: If the script is not registered.
        """
        metadata = self._version_mgr.get_metadata(name)
        if metadata is None:
            raise ValueError(f"Script '{name}' is not registered.")

        if new_path is not None:
            new_path = os.path.expanduser(new_path)
            if not os.path.isfile(new_path):
                raise FileNotFoundError(f"New script file not found: {new_path}")

            # Backup old version if content changed.
            if self._version_mgr.has_changed(name, new_path):
                try:
                    self._version_mgr.backup_version(name, metadata.path)
                except (FileNotFoundError, OSError) as exc:
                    logger.warning("Backup before update failed for '%s': %s", name, exc)

            # Copy new file to script_dir if needed.
            abs_new = os.path.abspath(new_path)
            abs_dir = os.path.abspath(self._script_dir)
            if not abs_new.startswith(abs_dir + os.sep):
                dest = os.path.join(self._script_dir, os.path.basename(new_path))
                try:
                    shutil.copy2(new_path, dest)
                except OSError as exc:
                    logger.error("Failed to copy updated script: %s", exc)
                    raise
                new_path = dest

            # Validate the final path is within the allowed directory.
            self._validate_script_path(new_path)

            metadata.path = new_path
            metadata.file_hash = self._version_mgr.compute_hash(new_path)

        # Apply extra metadata fields.
        for key, value in metadata_kwargs.items():
            if hasattr(metadata, key):
                setattr(metadata, key, value)

        self._version_mgr.update_metadata(metadata)
        logger.info("Updated script '%s'.", name)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_info(self, name: str) -> Optional[ScriptMetadata]:
        """Get full metadata for a registered script.

        Parameters:
            name: Registered script name.

        Returns:
            ``ScriptMetadata`` or ``None`` if not found.
        """
        return self._version_mgr.get_metadata(name)

    def list_scripts(self, category: Optional[str] = None) -> List[ScriptMetadata]:
        """List all registered scripts, optionally filtered by category.

        Parameters:
            category: If provided, only scripts with this category are returned.

        Returns:
            A list of ``ScriptMetadata`` instances.
        """
        try:
            records: list[ScriptMeta] = self._db.list_script_metas()
        except Exception as exc:
            logger.error("Database error listing scripts: %s", exc)
            return []

        results: List[ScriptMetadata] = []
        for rec in records:
            if category is not None and (rec.category or "") != category:
                continue
            results.append(
                ScriptMetadata(
                    name=rec.name,
                    path=rec.path,
                    author=rec.author or "",
                    description=rec.description or "",
                    category=rec.category or "",
                    venv_path=rec.venv_path or "",
                    file_hash=rec.file_hash or "",
                    version_count=rec.version_count,
                    created_at=rec.created_at,
                    updated_at=rec.updated_at,
                )
            )
        return results

    def get_script_path(self, name: str) -> Optional[str]:
        """Return the filesystem path for a registered script.

        Parameters:
            name: Registered script name.

        Returns:
            The script path string or ``None`` if not found.
        """
        metadata = self._version_mgr.get_metadata(name)
        if metadata is None:
            return None
        return metadata.path

    # ------------------------------------------------------------------
    # Directory scanning
    # ------------------------------------------------------------------

    def scan_directory(self) -> List[str]:
        """Scan the script directory for unregistered ``.py`` files.

        Returns:
            A list of absolute paths to ``.py`` files that are *not* yet
            registered in the database.
        """
        unregistered: List[str] = []

        try:
            registered_names: set[str] = set()
            registered_paths: set[str] = set()
            for rec in self._db.list_script_metas():
                registered_names.add(rec.name)
                registered_paths.add(os.path.abspath(rec.path))
        except Exception as exc:
            logger.error("Database error during scan: %s", exc)
            return []

        try:
            for filename in os.listdir(self._script_dir):
                if not filename.endswith(".py"):
                    continue
                filepath = os.path.abspath(os.path.join(self._script_dir, filename))
                if filepath not in registered_paths:
                    unregistered.append(filepath)
        except OSError as exc:
            logger.error("Failed to scan script directory %s: %s", self._script_dir, exc)

        return unregistered

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_script(self, script_path: str) -> Tuple[bool, str]:
        """Validate that a script is syntactically correct and can be executed.

        Checks performed:
        1. File existence.
        2. Python syntax (via ``py_compile``).
        3. If a ``venv_path`` is associated, verifies the venv directory exists.

        Parameters:
            script_path: Path to the script file.

        Returns:
            A ``(valid, message)`` tuple.
        """
        script_path = os.path.expanduser(script_path)

        if not os.path.isfile(script_path):
            return False, f"File not found: {script_path}"

        # Syntax check.
        try:
            py_compile.compile(script_path, doraise=True)
        except py_compile.PyCompileError as exc:
            return False, f"Syntax error: {exc}"

        # Venv check – look up metadata by scanning known scripts.
        script_name = os.path.splitext(os.path.basename(script_path))[0]
        metadata = self._version_mgr.get_metadata(script_name)
        if metadata and metadata.venv_path:
            venv = os.path.expanduser(metadata.venv_path)
            if not os.path.isdir(venv):
                return False, f"Virtual-environment not found: {venv}"

        return True, "Script is valid."

    # ------------------------------------------------------------------
    # Version operations
    # ------------------------------------------------------------------

    def get_versions(self, name: str) -> List[dict]:
        """Return the version history for a script.

        Parameters:
            name: Registered script name.

        Returns:
            A list of version dicts (see ``VersionManager.list_versions``).
        """
        return self._version_mgr.list_versions(name)

    def restore_version(self, name: str, version_path: str) -> bool:
        """Restore a script to a specific versioned backup.

        The current script file is overwritten with the contents of
        *version_path*.

        Parameters:
            name: Registered script name.
            version_path: Path to the backup file.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        metadata = self._version_mgr.get_metadata(name)
        if metadata is None:
            logger.error("Cannot restore: script '%s' is not registered.", name)
            return False

        target_path = metadata.path
        return self._version_mgr.restore_version(name, version_path, target_path)

    def check_and_backup(self, name: str) -> bool:
        """Check whether a script has changed and create a backup if so.

        Intended to be called before task execution to ensure the latest
        version is captured.

        Parameters:
            name: Registered script name.

        Returns:
            ``True`` if the script had changes and a backup was created,
            ``False`` otherwise.
        """
        metadata = self._version_mgr.get_metadata(name)
        if metadata is None:
            logger.warning("Script '%s' not found; skipping backup check.", name)
            return False

        if not os.path.isfile(metadata.path):
            logger.warning("Script file missing for '%s': %s", name, metadata.path)
            return False

        if not self._version_mgr.has_changed(name, metadata.path):
            logger.debug("No changes detected for script '%s'.", name)
            return False

        try:
            self._version_mgr.backup_version(name, metadata.path)
            logger.info("Auto-backup created for changed script '%s'.", name)
            return True
        except (FileNotFoundError, OSError) as exc:
            logger.error("Auto-backup failed for '%s': %s", name, exc)
            return False
