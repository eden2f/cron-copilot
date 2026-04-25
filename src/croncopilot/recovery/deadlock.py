"""Deadlock and long-running task detection for CronCopilot.

Provides :class:`DeadlockDetector` which periodically inspects running tasks
and identifies those that have exceeded their configured timeout, optionally
killing them automatically.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from croncopilot.config.schema import RecoveryConfig
from croncopilot.core.executor import RunningTaskInfo, TaskExecutor
from croncopilot.logging.logger import get_logger
from croncopilot.monitor.tracker import ExecutionTracker

logger = get_logger(__name__)


class DeadlockDetector:
    """Detect tasks that have been running longer than their timeout.

    Periodically queries the executor for running tasks and compares each
    task's elapsed time against its configured timeout.  Optionally kills
    timed-out tasks automatically.

    Parameters:
        config: Recovery subsystem configuration (provides
            ``task_timeout`` as the global default).
        executor: The task executor used to query and cancel tasks.
        tracker: Optional execution tracker (for future extensions).
        alert_callback: Called with a message string when a stuck task is
            detected.
    """

    def __init__(
        self,
        config: RecoveryConfig,
        executor: TaskExecutor,
        tracker: Optional[ExecutionTracker] = None,
        alert_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._config: RecoveryConfig = config
        self._executor: TaskExecutor = executor
        self._tracker: Optional[ExecutionTracker] = tracker
        self._alert: Optional[Callable[[str], None]] = alert_callback
        self._timer: Optional[threading.Timer] = None
        self._running: bool = False
        self._check_interval: int = 30
        self._detected_tasks: Dict[str, datetime] = {}  # task_id -> first_detected_time
        self._lock: threading.Lock = threading.Lock()

        # Configurable behaviour.
        self.auto_kill: bool = False  # Whether to automatically terminate timed-out tasks

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, check_interval: int = 30) -> None:
        """Start the periodic deadlock-detection loop.

        Parameters:
            check_interval: Seconds between consecutive detection runs.
        """
        with self._lock:
            if self._running:
                logger.warning("DeadlockDetector: already running")
                return
            self._running = True
            self._check_interval = check_interval
        logger.info(
            "DeadlockDetector: started (interval=%ds, auto_kill=%s)",
            check_interval,
            self.auto_kill,
        )
        self._detect_loop()

    def stop(self) -> None:
        """Stop the periodic detection loop."""
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        logger.info("DeadlockDetector: stopped")

    # ------------------------------------------------------------------
    # Internal scheduling
    # ------------------------------------------------------------------

    def _detect_loop(self) -> None:
        """Execute one detection pass and schedule the next iteration."""
        with self._lock:
            if not self._running:
                return

        self.detect()

        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._check_interval, self._detect_loop)
            self._timer.daemon = True
            self._timer.start()

    # ------------------------------------------------------------------
    # Core detection
    # ------------------------------------------------------------------

    def detect(self) -> List[Dict[str, Any]]:
        """Perform a single deadlock/timeout detection pass.

        Steps:

        1. Retrieve all running tasks from the executor.
        2. For each task, determine the effective timeout (task-level
           ``TaskConfig.timeout`` takes priority over the global
           ``config.task_timeout``).
        3. If the task's elapsed time exceeds the timeout:
           a. First detection: record the task and send an alert.
           b. If ``auto_kill`` is enabled: cancel the task via the executor.
        4. Tasks that are no longer running are purged from the detected set.

        Returns:
            A list of dicts describing timed-out tasks, each containing
            ``task_id``, ``task_name``, ``running_time``, ``timeout``, and
            ``action``.
        """
        running_tasks: Dict[str, RunningTaskInfo] = self._executor.get_running_tasks()
        now = datetime.now()
        timed_out: List[Dict[str, Any]] = []

        for task_id, info in running_tasks.items():
            elapsed = (now - info.start_time).total_seconds()

            # Effective timeout: task-level > global config.
            timeout = info.task_config.timeout if info.task_config.timeout > 0 else self._config.task_timeout

            if elapsed <= timeout:
                continue

            # Task has exceeded its timeout.
            action = "detected"

            with self._lock:
                first_detected = self._detected_tasks.get(task_id)
                if first_detected is None:
                    # First time we notice this task is stuck.
                    self._detected_tasks[task_id] = now
                    first_detected = now

            # Send alert on first detection.
            if first_detected == now:
                alert_msg = (
                    f"[Deadlock Alert] Task {task_id} ({info.task_config.name}) "
                    f"has been running for {elapsed:.0f}s "
                    f"(timeout: {timeout}s)"
                )
                logger.warning("DeadlockDetector: %s", alert_msg)

                if self._alert is not None:
                    try:
                        self._alert(alert_msg)
                    except Exception:
                        logger.exception(
                            "DeadlockDetector: alert callback raised for task %s",
                            task_id,
                        )

            # Auto-kill if enabled.
            if self.auto_kill:
                killed = self._do_kill(task_id)
                action = "killed" if killed else "kill_failed"

            timed_out.append(
                {
                    "task_id": task_id,
                    "task_name": info.task_config.name,
                    "running_time": round(elapsed, 2),
                    "timeout": timeout,
                    "action": action,
                }
            )

        # Purge detected entries for tasks that are no longer running.
        with self._lock:
            stale_ids = [
                tid for tid in self._detected_tasks if tid not in running_tasks
            ]
            for tid in stale_ids:
                self._detected_tasks.pop(tid, None)

        return timed_out

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_detected_tasks(self) -> Dict[str, Dict[str, Any]]:
        """Return information about currently detected stuck tasks.

        Returns:
            Dict mapping *task_id* to a dict containing ``first_detected``
            and ``elapsed`` (seconds since first detection).
        """
        now = datetime.now()
        with self._lock:
            return {
                tid: {
                    "first_detected": dt,
                    "elapsed": round((now - dt).total_seconds(), 2),
                }
                for tid, dt in self._detected_tasks.items()
            }

    # ------------------------------------------------------------------
    # Manual intervention
    # ------------------------------------------------------------------

    def force_kill(self, task_id: str) -> bool:
        """Manually force-kill a running task.

        Parameters:
            task_id: Unique task identifier.

        Returns:
            ``True`` if the task was successfully cancelled, ``False``
            otherwise.
        """
        logger.info("DeadlockDetector: manual force-kill requested for task %s", task_id)
        return self._do_kill(task_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_kill(self, task_id: str) -> bool:
        """Attempt to cancel a task via the executor.

        Parameters:
            task_id: Unique task identifier.

        Returns:
            ``True`` if the cancel signal was sent successfully.
        """
        try:
            cancelled = self._executor.cancel_task(task_id)
            if cancelled:
                logger.info(
                    "DeadlockDetector: task %s killed successfully", task_id
                )
                with self._lock:
                    self._detected_tasks.pop(task_id, None)
            else:
                logger.warning(
                    "DeadlockDetector: failed to kill task %s", task_id
                )
            return cancelled
        except Exception:
            logger.exception(
                "DeadlockDetector: error killing task %s", task_id
            )
            return False
