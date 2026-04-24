"""Automatic retry management with exponential backoff and rollback support.

Provides :class:`RetryManager` which integrates with
:class:`~pycronguard.core.executor.TaskExecutor` to automatically retry
failed tasks and optionally execute rollback handlers when retries are
exhausted.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from pycronguard.config.schema import RecoveryConfig
from pycronguard.core.executor import TaskExecutor
from pycronguard.core.task import TaskConfig
from pycronguard.logging.logger import get_logger
from pycronguard.monitor.tracker import ExecutionTracker
from pycronguard.storage.database import DatabaseManager

logger = get_logger(__name__)


class RetryManager:
    """Automatic retry manager with exponential backoff and rollback support.

    Monitors task execution outcomes and automatically retries failed tasks
    up to the configured maximum number of attempts.  When all retries are
    exhausted, an optional rollback handler is invoked.

    Parameters:
        config: Recovery subsystem configuration.
        executor: The task executor used to resubmit tasks.
        db_manager: Database manager for persistence.
        tracker: Optional execution tracker for querying failure history.
    """

    def __init__(
        self,
        config: RecoveryConfig,
        executor: TaskExecutor,
        db_manager: DatabaseManager,
        tracker: Optional[ExecutionTracker] = None,
    ) -> None:
        self._config: RecoveryConfig = config
        self._executor: TaskExecutor = executor
        self._db: DatabaseManager = db_manager
        self._tracker: Optional[ExecutionTracker] = tracker
        self._retry_counts: Dict[str, int] = {}  # task_id -> current_retry_count
        self._rollback_handlers: Dict[str, Callable[[], bool]] = {}  # task_id -> rollback_function
        self._task_configs: Dict[str, TaskConfig] = {}  # task_id -> TaskConfig (cached for retry)
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Rollback registration
    # ------------------------------------------------------------------

    def register_rollback(self, task_id: str, handler: Callable[[], bool]) -> None:
        """Register a rollback handler for a task.

        The handler is invoked when all retry attempts have been exhausted.

        Parameters:
            task_id: Unique task identifier.
            handler: A callable ``() -> bool`` that returns ``True`` if the
                rollback completed successfully.
        """
        with self._lock:
            self._rollback_handlers[task_id] = handler
        logger.info("RetryManager: registered rollback handler for task %s", task_id)

    def unregister_rollback(self, task_id: str) -> None:
        """Remove a previously registered rollback handler.

        Parameters:
            task_id: Unique task identifier.
        """
        with self._lock:
            removed = self._rollback_handlers.pop(task_id, None)
        if removed is not None:
            logger.info("RetryManager: unregistered rollback handler for task %s", task_id)

    # ------------------------------------------------------------------
    # Core retry logic
    # ------------------------------------------------------------------

    def on_task_failed(self, task_id: str, task_config: TaskConfig, error: str) -> None:
        """Handle a task failure – retry or rollback.

        This is the main entry point invoked when a task execution fails.

        1. Determines the effective ``max_retries`` (task-level config takes
           priority over global config).
        2. If retries remain, computes an exponential-backoff delay and
           schedules the task for re-execution.
        3. If retries are exhausted, executes the rollback handler (if
           registered) and cleans up internal state.

        Parameters:
            task_id: Unique task identifier.
            task_config: Configuration of the failed task.
            error: Human-readable error description.
        """
        with self._lock:
            current_count = self._retry_counts.get(task_id, 0)
            # Cache the task config for delayed retry submission.
            self._task_configs[task_id] = task_config

        # Task-level max_retries takes priority; fall back to global config.
        max_retries = task_config.max_retries if task_config.max_retries > 0 else self._config.max_retries

        if current_count < max_retries:
            # Calculate exponential backoff delay.
            delay = self._config.retry_delay * (self._config.backoff_factor ** current_count)

            with self._lock:
                self._retry_counts[task_id] = current_count + 1

            logger.warning(
                "RetryManager: task %s (%s) failed (attempt %d/%d). "
                "Retrying in %.1fs. Error: %s",
                task_id,
                task_config.name,
                current_count + 1,
                max_retries,
                delay,
                error[:200] if error else "N/A",
            )

            self._schedule_retry(task_config, delay)
        else:
            logger.error(
                "RetryManager: task %s (%s) failed after %d retries. "
                "No more retries. Error: %s",
                task_id,
                task_config.name,
                max_retries,
                error[:200] if error else "N/A",
            )

            # Attempt rollback.
            self._execute_rollback(task_id)

            # Clean up.
            with self._lock:
                self._retry_counts.pop(task_id, None)
                self._task_configs.pop(task_id, None)

    def _schedule_retry(self, task_config: TaskConfig, delay: float) -> None:
        """Schedule a delayed retry by resubmitting the task to the executor.

        Uses :class:`threading.Timer` to implement the delay.

        Parameters:
            task_config: Configuration of the task to retry.
            delay: Seconds to wait before resubmission.
        """

        def _retry() -> None:
            logger.info(
                "RetryManager: resubmitting task %s (%s) after %.1fs delay",
                task_config.task_id,
                task_config.name,
                delay,
            )
            try:
                submitted = self._executor.submit(task_config)
                if not submitted:
                    logger.error(
                        "RetryManager: failed to resubmit task %s (%s)",
                        task_config.task_id,
                        task_config.name,
                    )
            except Exception:
                logger.exception(
                    "RetryManager: unexpected error resubmitting task %s",
                    task_config.task_id,
                )

        timer = threading.Timer(delay, _retry)
        timer.daemon = True
        timer.start()

    def _execute_rollback(self, task_id: str) -> bool:
        """Execute the registered rollback handler for a task.

        The call is exception-safe; any errors raised by the handler are
        logged but not propagated.

        Parameters:
            task_id: Unique task identifier.

        Returns:
            ``True`` if the rollback handler succeeded (or no handler was
            registered), ``False`` if the handler raised or returned
            ``False``.
        """
        with self._lock:
            handler = self._rollback_handlers.get(task_id)

        if handler is None:
            logger.debug("RetryManager: no rollback handler for task %s", task_id)
            return True

        logger.info("RetryManager: executing rollback for task %s", task_id)
        try:
            success = handler()
            if success:
                logger.info("RetryManager: rollback succeeded for task %s", task_id)
            else:
                logger.warning("RetryManager: rollback returned False for task %s", task_id)
            return bool(success)
        except Exception:
            logger.exception("RetryManager: rollback handler raised for task %s", task_id)
            return False

    # ------------------------------------------------------------------
    # Query / reset helpers
    # ------------------------------------------------------------------

    def get_retry_count(self, task_id: str) -> int:
        """Return the current retry count for a task.

        Parameters:
            task_id: Unique task identifier.

        Returns:
            Number of retries that have been attempted so far.
        """
        with self._lock:
            return self._retry_counts.get(task_id, 0)

    def reset_retry_count(self, task_id: str) -> None:
        """Reset the retry counter for a task.

        Should be called when a task succeeds so that subsequent failures
        start from zero again.

        Parameters:
            task_id: Unique task identifier.
        """
        with self._lock:
            removed = self._retry_counts.pop(task_id, None)
            self._task_configs.pop(task_id, None)
        if removed is not None:
            logger.debug("RetryManager: reset retry count for task %s", task_id)

    # ------------------------------------------------------------------
    # Executor binding
    # ------------------------------------------------------------------

    def bind_executor(self, executor: TaskExecutor) -> None:
        """Bind this retry manager to a :class:`TaskExecutor`.

        Wraps the executor's ``on_task_complete`` callback so that:

        * On failure: :meth:`on_task_failed` is triggered automatically.
        * On success: the retry counter is reset.

        Existing callbacks (e.g. from the tracker or alert manager) are
        preserved and called first.

        Parameters:
            executor: The executor to bind to.
        """
        original_on_complete = executor.on_task_complete

        def _wrapped_on_complete(task_id: str, success: bool, result: Any) -> None:
            # Call the original callback chain first (tracker, alert, etc.).
            if original_on_complete is not None:
                try:
                    original_on_complete(task_id, success, result)
                except Exception:
                    logger.exception(
                        "RetryManager: original on_task_complete hook failed for task %s",
                        task_id,
                    )

            if success:
                self.reset_retry_count(task_id)
            else:
                # Retrieve the task_config from the running-tasks snapshot
                # that was captured *before* the executor cleaned it up.
                # Fall back to the cached config from a previous retry.
                task_config: Optional[TaskConfig] = None

                # The executor stores RunningTaskInfo which contains task_config.
                # However, by the time on_task_complete fires the task has been
                # removed from _running_tasks.  We therefore rely on the cached
                # config stored during a previous on_task_failed call, or look it
                # up from the database.
                with self._lock:
                    task_config = self._task_configs.get(task_id)

                if task_config is None:
                    # Try to reconstruct from DB.
                    try:
                        from pycronguard.core.task import record_to_task_config

                        record = self._db.get_task(task_id)
                        if record is not None:
                            task_config = record_to_task_config(record)
                    except Exception:
                        logger.exception(
                            "RetryManager: could not retrieve task config for %s",
                            task_id,
                        )

                if task_config is None:
                    logger.error(
                        "RetryManager: cannot retry task %s — config unavailable",
                        task_id,
                    )
                    return

                error_msg = ""
                if isinstance(result, dict):
                    error_msg = result.get("stderr", "") or result.get("error", "") or ""

                self.on_task_failed(task_id, task_config, str(error_msg))

        executor.on_task_complete = _wrapped_on_complete
        self._executor = executor
        logger.info("RetryManager: bound to TaskExecutor")
