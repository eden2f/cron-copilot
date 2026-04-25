"""Database manager providing session handling and CRUD helpers.

Wraps SQLAlchemy engine/session creation and exposes typed convenience
methods for each ORM model.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import Session, sessionmaker

from pycronguard.storage.models import (
    AlertLog,
    Base,
    ScriptMeta,
    TaskExecution,
    TaskRecord,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manage the SQLite database lifecycle and expose CRUD operations.

    Parameters:
        db_path: Path to the SQLite database file.  Parent directories are
            created automatically if they do not exist.
    """

    def __init__(self, db_path: str) -> None:
        db_path = os.path.expanduser(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

        # Create tables if they don't exist yet.
        Base.metadata.create_all(self._engine)

        # 自动迁移：为已有表添加新列
        import sqlalchemy
        with self._engine.connect() as conn:
            inspector = sqlalchemy.inspect(self._engine)
            columns = [c['name'] for c in inspector.get_columns('tasks')]
            if 'holiday_mode' not in columns:
                conn.execute(sqlalchemy.text(
                    "ALTER TABLE tasks ADD COLUMN holiday_mode VARCHAR(32) DEFAULT 'none'"
                ))
                conn.commit()
                logger.info("Migrated: added holiday_mode column to tasks table")

        logger.info("Database initialised at %s", db_path)

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Provide a transactional session scope.

        Yields:
            Session: An active SQLAlchemy session that is committed on
            success and rolled back on error.
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # TaskRecord CRUD
    # ------------------------------------------------------------------

    def add_task(self, task: TaskRecord) -> None:
        """Insert a new task record.

        Parameters:
            task: The ``TaskRecord`` instance to persist.
        """
        with self.get_session() as session:
            session.add(task)

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Fetch a task by its primary key.

        Parameters:
            task_id: UUID of the task.

        Returns:
            The matching ``TaskRecord`` or *None*.
        """
        with self.get_session() as session:
            return session.get(TaskRecord, task_id)

    def get_task_by_name(self, name: str) -> TaskRecord | None:
        """Fetch a task by its unique name.

        Parameters:
            name: Task name.

        Returns:
            The matching ``TaskRecord`` or *None*.
        """
        with self.get_session() as session:
            return session.query(TaskRecord).filter_by(name=name).first()

    def list_tasks(self) -> list[TaskRecord]:
        """Return all registered tasks.

        Returns:
            List of ``TaskRecord`` instances.
        """
        with self.get_session() as session:
            return list(session.query(TaskRecord).all())

    def update_task(self, task_id: str, **kwargs: object) -> None:
        """Update fields of an existing task.

        Parameters:
            task_id: UUID of the task.
            **kwargs: Field names and their new values.
        """
        with self.get_session() as session:
            session.query(TaskRecord).filter_by(id=task_id).update(kwargs)

    def delete_task(self, task_id: str) -> None:
        """Delete a task by its primary key.

        Parameters:
            task_id: UUID of the task.
        """
        with self.get_session() as session:
            task = session.get(TaskRecord, task_id)
            if task:
                session.delete(task)

    # ------------------------------------------------------------------
    # TaskExecution CRUD
    # ------------------------------------------------------------------

    def add_execution(self, execution: TaskExecution) -> None:
        """Insert a new execution record.

        Parameters:
            execution: The ``TaskExecution`` instance to persist.
        """
        with self.get_session() as session:
            session.add(execution)

    def get_latest_execution(self, task_id: str) -> TaskExecution | None:
        """Get the most recent execution for a task.

        Parameters:
            task_id: UUID of the parent task.

        Returns:
            The latest ``TaskExecution`` or *None*.
        """
        with self.get_session() as session:
            return (
                session.query(TaskExecution)
                .filter_by(task_id=task_id)
                .order_by(desc(TaskExecution.id))
                .first()
            )

    def list_executions(self, task_id: str, limit: int = 50) -> list[TaskExecution]:
        """List recent executions for a task.

        Parameters:
            task_id: UUID of the parent task.
            limit: Maximum number of records to return.

        Returns:
            List of ``TaskExecution`` instances, newest first.
        """
        with self.get_session() as session:
            return list(
                session.query(TaskExecution)
                .filter_by(task_id=task_id)
                .order_by(desc(TaskExecution.id))
                .limit(limit)
                .all()
            )

    # ------------------------------------------------------------------
    # ScriptMeta CRUD
    # ------------------------------------------------------------------

    def add_script_meta(self, meta: ScriptMeta) -> None:
        """Insert a new script metadata record.

        Parameters:
            meta: The ``ScriptMeta`` instance to persist.
        """
        with self.get_session() as session:
            session.add(meta)

    def get_script_meta(self, name: str) -> ScriptMeta | None:
        """Fetch script metadata by name.

        Parameters:
            name: Unique script name.

        Returns:
            The matching ``ScriptMeta`` or *None*.
        """
        with self.get_session() as session:
            return session.query(ScriptMeta).filter_by(name=name).first()

    def list_script_metas(self) -> list[ScriptMeta]:
        """Return all script metadata records.

        Returns:
            List of ``ScriptMeta`` instances.
        """
        with self.get_session() as session:
            return list(session.query(ScriptMeta).all())

    def update_script_meta(self, name: str, **kwargs: object) -> None:
        """Update fields of a script metadata record.

        Parameters:
            name: Unique script name.
            **kwargs: Field names and their new values.
        """
        with self.get_session() as session:
            session.query(ScriptMeta).filter_by(name=name).update(kwargs)

    def delete_script_meta(self, name: str) -> None:
        """Delete a script metadata record by name.

        Parameters:
            name: Unique script name.
        """
        with self.get_session() as session:
            meta = session.query(ScriptMeta).filter_by(name=name).first()
            if meta:
                session.delete(meta)

    # ------------------------------------------------------------------
    # AlertLog CRUD
    # ------------------------------------------------------------------

    def add_alert_log(self, log: AlertLog) -> None:
        """Insert a new alert log entry.

        Parameters:
            log: The ``AlertLog`` instance to persist.
        """
        with self.get_session() as session:
            session.add(log)

    def list_alert_logs(
        self, task_id: str | None = None, limit: int = 50
    ) -> list[AlertLog]:
        """List recent alert log entries.

        Parameters:
            task_id: If provided, filter by task UUID.
            limit: Maximum number of records to return.

        Returns:
            List of ``AlertLog`` instances, newest first.
        """
        with self.get_session() as session:
            query = session.query(AlertLog)
            if task_id is not None:
                query = query.filter_by(task_id=task_id)
            return list(query.order_by(desc(AlertLog.id)).limit(limit).all())
