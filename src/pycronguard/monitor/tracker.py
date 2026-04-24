"""Execution status tracker for PyCronGuard tasks.

Integrates with :class:`~pycronguard.core.executor.TaskExecutor` callback
hooks to record task lifecycle events and maintain an in-memory view of
active executions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from pycronguard.core.task import TaskConfig
from pycronguard.logging.logger import get_logger
from pycronguard.storage.database import DatabaseManager
from pycronguard.storage.models import TaskExecution

logger = get_logger(__name__)


class ExecutionTracker:
    """Track task execution state and persist records via *DatabaseManager*.

    Parameters:
        db_manager: The database manager used for persistence.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db: DatabaseManager = db_manager
        self._active_executions: Dict[str, TaskExecution] = {}
        # Optional post-complete callback (set by AlertManager.bind_tracker).
        self._on_complete_callback: Optional[Callable[[str, TaskExecution], None]] = None

    # ------------------------------------------------------------------
    # Callback hooks
    # ------------------------------------------------------------------

    def on_task_start(self, task_id: str, task_config: TaskConfig) -> None:
        """Record the start of a task execution.

        Intended to be registered as the
        :pyattr:`TaskExecutor.on_task_start` callback.

        Parameters:
            task_id: Unique task identifier.
            task_config: Configuration of the task being started.
        """
        try:
            execution = TaskExecution(
                task_id=task_id,
                status="running",
                start_time=datetime.now(),
            )
            self._db.add_execution(execution)
            self._active_executions[task_id] = execution
            logger.info("Tracker: task %s (%s) started", task_id, task_config.name)
        except Exception:
            logger.exception("Tracker: failed to record start for task %s", task_id)

    def on_task_complete(self, task_id: str, success: bool, result: Any) -> TaskExecution | None:
        """Record the completion of a task execution.

        Intended to be registered as the
        :pyattr:`TaskExecutor.on_task_complete` callback.

        Parameters:
            task_id: Unique task identifier.
            success: Whether the task completed successfully.
            result: A dict containing ``return_code``, ``stdout``/``stderr``,
                ``duration``, and optionally ``cpu_usage`` / ``memory_usage``.

        Returns:
            The completed :class:`TaskExecution` record, or ``None`` on error.
        """
        try:
            status = "success" if success else "failed"
            end_time = datetime.now()

            # Extract fields from the result dict (may be None).
            return_code: int | None = None
            output: str | None = None
            error: str | None = None
            duration: float | None = None
            cpu_usage: float | None = None
            memory_usage: float | None = None

            if isinstance(result, dict):
                return_code = result.get("return_code")
                output = result.get("stdout") or result.get("output")
                error = result.get("stderr") or result.get("error")
                duration = result.get("duration")
                cpu_usage = result.get("cpu_usage")
                memory_usage = result.get("memory_usage")

            execution = TaskExecution(
                task_id=task_id,
                status=status,
                start_time=self._active_executions.get(task_id, TaskExecution(task_id=task_id)).start_time,
                end_time=end_time,
                duration=duration,
                return_code=return_code,
                output=(output or "")[:10000] if output else None,
                error=(error or "")[:10000] if error else None,
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
            )
            self._db.add_execution(execution)

            # Remove from active set.
            self._active_executions.pop(task_id, None)

            logger.info(
                "Tracker: task %s completed with status=%s (duration=%.2fs)",
                task_id,
                status,
                duration or 0.0,
            )

            # Notify alert manager (if bound).
            if self._on_complete_callback is not None:
                try:
                    self._on_complete_callback(task_id, execution)
                except Exception:
                    logger.exception("Tracker: on_complete_callback failed for task %s", task_id)

            return execution

        except Exception:
            logger.exception("Tracker: failed to record completion for task %s", task_id)
            self._active_executions.pop(task_id, None)
            return None

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_active_executions(self) -> Dict[str, TaskExecution]:
        """Return a copy of the currently active executions map.

        Returns:
            Dict mapping *task_id* to its running :class:`TaskExecution`.
        """
        return dict(self._active_executions)

    def get_task_history(self, task_id: str, limit: int = 50) -> List[TaskExecution]:
        """Return recent execution records for a task.

        Parameters:
            task_id: Unique task identifier.
            limit: Maximum number of records to return.

        Returns:
            List of :class:`TaskExecution` instances, newest first.
        """
        try:
            return self._db.list_executions(task_id, limit=limit)
        except Exception:
            logger.exception("Tracker: failed to fetch history for task %s", task_id)
            return []

    def get_task_status(self, task_id: str) -> Optional[str]:
        """Return the current status of a task.

        If the task is currently running, returns ``"running"``.  Otherwise
        returns the status of the most recent execution (``"success"`` or
        ``"failed"``), or ``None`` if no execution records exist.

        Parameters:
            task_id: Unique task identifier.

        Returns:
            Status string or ``None``.
        """
        if task_id in self._active_executions:
            return "running"
        try:
            latest = self._db.get_latest_execution(task_id)
            return latest.status if latest else None
        except Exception:
            logger.exception("Tracker: failed to get status for task %s", task_id)
            return None

    def get_consecutive_failures(self, task_id: str) -> int:
        """Count the number of consecutive recent failures for a task.

        Iterates through the execution history (newest first) and counts
        entries with ``status == 'failed'`` until a non-failure is found.

        Parameters:
            task_id: Unique task identifier.

        Returns:
            Number of consecutive failures (0 if the last run succeeded).
        """
        try:
            history = self._db.list_executions(task_id, limit=100)
            count = 0
            for execution in history:
                if execution.status == "failed":
                    count += 1
                elif execution.status in ("success", "running"):
                    break
            return count
        except Exception:
            logger.exception("Tracker: failed to count failures for task %s", task_id)
            return 0

    # ------------------------------------------------------------------
    # Executor binding
    # ------------------------------------------------------------------

    def bind_executor(self, executor: "TaskExecutor") -> None:  # noqa: F821
        """Bind this tracker to a :class:`TaskExecutor` instance.

        Replaces the executor's ``on_task_start`` and ``on_task_complete``
        callbacks so that execution events are automatically tracked.

        Parameters:
            executor: The executor to bind to.
        """
        from pycronguard.core.executor import TaskExecutor  # local import to avoid circular

        original_on_complete = executor.on_task_complete

        executor.on_task_start = self.on_task_start

        def _wrapped_on_complete(task_id: str, success: bool, result: Any) -> None:
            # Call original callback first (if any).
            if original_on_complete is not None:
                try:
                    original_on_complete(task_id, success, result)
                except Exception:
                    logger.exception("Original on_task_complete hook failed for task %s", task_id)
            # Then track via our handler.
            self.on_task_complete(task_id, success, result)

        executor.on_task_complete = _wrapped_on_complete

        logger.info("Tracker: bound to TaskExecutor")
