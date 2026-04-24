"""Script version control and metadata management.

Provides ``ScriptMetadata`` dataclass and ``VersionManager`` for tracking
script changes, creating versioned backups, and restoring previous versions.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from pycronguard.logging.logger import get_logger
from pycronguard.storage.database import DatabaseManager
from pycronguard.storage.models import ScriptMeta

logger = get_logger(__name__)


@dataclass
class ScriptMetadata:
    """Script metadata used for in-memory representation.

    Attributes:
        name: Unique script identifier.
        path: Absolute filesystem path to the script file.
        author: Author of the script.
        description: Human-readable description.
        category: Logical category / tag.
        venv_path: Path to the Python virtual-environment for this script.
        file_hash: SHA-256 hex digest of the script contents.
        version_count: Number of versioned backups that exist.
        created_at: Timestamp when the script was first registered.
        updated_at: Timestamp of the most recent metadata change.
    """

    name: str = ""
    path: str = ""
    author: str = ""
    description: str = ""
    category: str = ""
    venv_path: str = ""
    file_hash: str = ""
    version_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class VersionManager:
    """Manage versioned backups and metadata for registered scripts.

    Parameters:
        version_dir: Root directory where versioned backups are stored.
        max_versions: Maximum number of backup versions to keep per script.
        db_manager: Optional ``DatabaseManager`` instance for persisting metadata.
    """

    def __init__(
        self,
        version_dir: str,
        max_versions: int = 10,
        db_manager: Optional[DatabaseManager] = None,
    ) -> None:
        self._version_dir: str = os.path.expanduser(version_dir)
        self._max_versions: int = max_versions
        self._db: Optional[DatabaseManager] = db_manager

        os.makedirs(self._version_dir, exist_ok=True)
        logger.debug("VersionManager initialised (version_dir=%s)", self._version_dir)

    # ------------------------------------------------------------------
    # Hash helpers
    # ------------------------------------------------------------------

    def compute_hash(self, file_path: str) -> str:
        """Compute the SHA-256 hex digest of a file.

        Parameters:
            file_path: Path to the file.

        Returns:
            The hex-encoded SHA-256 hash string.

        Raises:
            FileNotFoundError: If *file_path* does not exist.
            OSError: On read failure.
        """
        file_path = os.path.expanduser(file_path)
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    sha256.update(chunk)
        except FileNotFoundError:
            logger.error("File not found when computing hash: %s", file_path)
            raise
        except OSError as exc:
            logger.error("Failed to read file for hashing: %s – %s", file_path, exc)
            raise
        return sha256.hexdigest()

    def has_changed(self, script_name: str, file_path: str) -> bool:
        """Check whether a script file has changed since the last recorded hash.

        Parameters:
            script_name: Registered name of the script.
            file_path: Current filesystem path to compare.

        Returns:
            ``True`` if the file hash differs from the stored value or if no
            previous record exists; ``False`` otherwise.
        """
        file_path = os.path.expanduser(file_path)
        try:
            current_hash = self.compute_hash(file_path)
        except (FileNotFoundError, OSError):
            return True

        metadata = self.get_metadata(script_name)
        if metadata is None or not metadata.file_hash:
            return True

        return current_hash != metadata.file_hash

    # ------------------------------------------------------------------
    # Backup / restore
    # ------------------------------------------------------------------

    def backup_version(self, script_name: str, file_path: str) -> str:
        """Create a versioned backup of a script file.

        The backup is stored under
        ``<version_dir>/<script_name>/<timestamp>_<short_hash>.py``.

        Parameters:
            script_name: Registered name of the script.
            file_path: Path to the script file to back up.

        Returns:
            Absolute path to the newly created backup file.

        Raises:
            FileNotFoundError: If *file_path* does not exist.
            OSError: On copy / directory-creation failure.
        """
        file_path = os.path.expanduser(file_path)
        file_hash = self.compute_hash(file_path)
        short_hash = file_hash[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        script_version_dir = os.path.join(self._version_dir, script_name)
        try:
            os.makedirs(script_version_dir, exist_ok=True)
        except OSError as exc:
            logger.error("Cannot create version directory %s: %s", script_version_dir, exc)
            raise

        backup_filename = f"{timestamp}_{short_hash}.py"
        backup_path = os.path.join(script_version_dir, backup_filename)

        try:
            shutil.copy2(file_path, backup_path)
        except OSError as exc:
            logger.error("Failed to backup %s to %s: %s", file_path, backup_path, exc)
            raise

        logger.info(
            "Backed up script '%s' -> %s (hash=%s)",
            script_name,
            backup_path,
            short_hash,
        )

        # Update metadata in DB.
        self._update_hash_and_count(script_name, file_hash)

        # Cleanup old versions.
        self._cleanup_old_versions(script_name)

        return backup_path

    def _cleanup_old_versions(self, script_name: str) -> None:
        """Remove old backups exceeding ``max_versions`` (keep newest).

        Parameters:
            script_name: Registered name of the script.
        """
        script_version_dir = os.path.join(self._version_dir, script_name)
        if not os.path.isdir(script_version_dir):
            return

        try:
            files = sorted(
                [
                    f
                    for f in os.listdir(script_version_dir)
                    if os.path.isfile(os.path.join(script_version_dir, f))
                ],
            )
        except OSError as exc:
            logger.warning("Failed to list versions for '%s': %s", script_name, exc)
            return

        if len(files) <= self._max_versions:
            return

        to_remove = files[: len(files) - self._max_versions]
        for name in to_remove:
            path = os.path.join(script_version_dir, name)
            try:
                os.remove(path)
                logger.debug("Removed old version: %s", path)
            except OSError as exc:
                logger.warning("Failed to remove old version %s: %s", path, exc)

    def list_versions(self, script_name: str) -> List[dict]:
        """List all versioned backups of a script.

        Parameters:
            script_name: Registered name of the script.

        Returns:
            A list of dicts each containing ``version_path``, ``timestamp``
            and ``hash`` keys, sorted oldest-first.
        """
        script_version_dir = os.path.join(self._version_dir, script_name)
        if not os.path.isdir(script_version_dir):
            return []

        versions: List[dict] = []
        try:
            for filename in sorted(os.listdir(script_version_dir)):
                filepath = os.path.join(script_version_dir, filename)
                if not os.path.isfile(filepath):
                    continue
                # Expected format: YYYYMMDD_HHMMSS_<hash>.py
                base = filename.rsplit(".", 1)[0]  # strip .py
                parts = base.split("_", 2)
                if len(parts) >= 3:
                    timestamp_str = f"{parts[0]}_{parts[1]}"
                    hash_str = parts[2]
                else:
                    timestamp_str = base
                    hash_str = ""
                versions.append(
                    {
                        "version_path": filepath,
                        "timestamp": timestamp_str,
                        "hash": hash_str,
                    }
                )
        except OSError as exc:
            logger.warning("Failed to list versions for '%s': %s", script_name, exc)

        return versions

    def restore_version(self, script_name: str, version_path: str, target_path: str) -> bool:
        """Restore a specific versioned backup to *target_path*.

        Parameters:
            script_name: Registered name of the script (for logging).
            version_path: Path to the backup file to restore from.
            target_path: Destination path where the file should be written.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        version_path = os.path.expanduser(version_path)
        target_path = os.path.expanduser(target_path)

        if not os.path.isfile(version_path):
            logger.error("Version file not found: %s", version_path)
            return False

        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(version_path, target_path)
        except OSError as exc:
            logger.error(
                "Failed to restore version %s -> %s: %s",
                version_path,
                target_path,
                exc,
            )
            return False

        # Update the stored hash after restoring.
        try:
            new_hash = self.compute_hash(target_path)
            self._update_hash_and_count(script_name, new_hash)
        except (FileNotFoundError, OSError):
            pass  # non-fatal: metadata update failure shouldn't block restore

        logger.info(
            "Restored script '%s' from %s to %s",
            script_name,
            version_path,
            target_path,
        )
        return True

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def get_metadata(self, script_name: str) -> Optional[ScriptMetadata]:
        """Retrieve script metadata from the database.

        Parameters:
            script_name: Registered name of the script.

        Returns:
            A ``ScriptMetadata`` instance, or ``None`` if not found.
        """
        if self._db is None:
            logger.warning("No DatabaseManager configured; cannot fetch metadata.")
            return None

        try:
            record: Optional[ScriptMeta] = self._db.get_script_meta(script_name)
        except Exception as exc:
            logger.error("Database error fetching metadata for '%s': %s", script_name, exc)
            return None

        if record is None:
            return None

        return ScriptMetadata(
            name=record.name,
            path=record.path,
            author=record.author or "",
            description=record.description or "",
            category=record.category or "",
            venv_path=record.venv_path or "",
            file_hash=record.file_hash or "",
            version_count=record.version_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def update_metadata(self, metadata: ScriptMetadata) -> None:
        """Persist script metadata to the database.

        If a record for the given script name already exists it is updated;
        otherwise a new record is created.

        Parameters:
            metadata: The ``ScriptMetadata`` to save.
        """
        if self._db is None:
            logger.warning("No DatabaseManager configured; cannot update metadata.")
            return

        try:
            existing: Optional[ScriptMeta] = self._db.get_script_meta(metadata.name)
            if existing is None:
                record = ScriptMeta(
                    name=metadata.name,
                    path=metadata.path,
                    author=metadata.author or None,
                    description=metadata.description or None,
                    category=metadata.category or None,
                    venv_path=metadata.venv_path or None,
                    file_hash=metadata.file_hash or None,
                    version_count=metadata.version_count,
                )
                self._db.add_script_meta(record)
                logger.info("Created metadata record for script '%s'.", metadata.name)
            else:
                self._db.update_script_meta(
                    metadata.name,
                    path=metadata.path,
                    author=metadata.author or None,
                    description=metadata.description or None,
                    category=metadata.category or None,
                    venv_path=metadata.venv_path or None,
                    file_hash=metadata.file_hash or None,
                    version_count=metadata.version_count,
                )
                logger.info("Updated metadata record for script '%s'.", metadata.name)
        except Exception as exc:
            logger.error("Database error updating metadata for '%s': %s", metadata.name, exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_hash_and_count(self, script_name: str, file_hash: str) -> None:
        """Update the file hash and bump version count in the database.

        Parameters:
            script_name: Registered name of the script.
            file_hash: New SHA-256 hex digest.
        """
        if self._db is None:
            return

        try:
            existing = self._db.get_script_meta(script_name)
            if existing is not None:
                new_count = (existing.version_count or 0) + 1
                self._db.update_script_meta(
                    script_name,
                    file_hash=file_hash,
                    version_count=new_count,
                )
        except Exception as exc:
            logger.error(
                "Failed to update hash/version_count for '%s': %s",
                script_name,
                exc,
            )
