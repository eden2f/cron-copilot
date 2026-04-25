"""Concurrent task executor with priority queue and dependency checking.

Provides ``TaskExecutor`` which manages a thread pool, a heap-based priority
queue, and subprocess-based script execution with timeout / cancel support.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import heapq

from croncopilot.core.task import TaskConfig
from croncopilot.logging.logger import get_logger
from croncopilot.storage.database import DatabaseManager
from croncopilot.storage.models import TaskExecution
from croncopilot.core.holiday import get_holiday_checker

logger = get_logger(__name__)


@dataclass
class RunningTaskInfo:
    """Runtime information about a task that is currently executing.

    Attributes:
        task_id: The unique task identifier.
        task_config: The full task configuration.
        process: The ``subprocess.Popen`` handle (may be ``None`` before
            the subprocess is spawned).
        start_time: When execution started.
        thread_future: The ``Future`` returned by the thread pool.
    """

    task_id: str = ""
    task_config: TaskConfig = field(default_factory=TaskConfig)
    process: Optional[subprocess.Popen] = field(default=None, repr=False)  # type: ignore[type-arg]
    start_time: datetime = field(default_factory=datetime.now)
    thread_future: Optional[Future] = field(default=None, repr=False)  # type: ignore[type-arg]


class TaskExecutor:
    """Task executor supporting a priority queue and concurrency control.

    Parameters:
        max_workers: Maximum number of tasks that can run concurrently.
        db_manager: Optional ``DatabaseManager`` used for dependency checks
            and execution recording.
    """

    def __init__(
        self,
        max_workers: int = 4,
        db_manager: Optional[DatabaseManager] = None,
        record_to_db: bool = True,
    ) -> None:
        self._max_workers = max_workers
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._semaphore = threading.Semaphore(max_workers)
        self._running_tasks: Dict[str, RunningTaskInfo] = {}
        self._priority_queue: List[Tuple[int, float, TaskConfig]] = []
        self._lock = threading.Lock()
        self._db = db_manager
        self._record_to_db = record_to_db
        self._shutdown = False

        # Callback hooks – may be set by external modules (e.g. monitoring).
        self.on_task_start: Optional[Callable[[str, TaskConfig], None]] = None
        self.on_task_complete: Optional[Callable[[str, bool, Any], None]] = None

        logger.info("TaskExecutor initialised with max_workers=%d", max_workers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, task_config: TaskConfig) -> bool:
        """Submit a task to the priority queue for execution.

        The task is validated against its concurrency limit
        (``max_instances``) and dependency requirements before being
        enqueued.

        Parameters:
            task_config: Configuration of the task to submit.

        Returns:
            ``True`` if the task was enqueued successfully, ``False``
            otherwise (e.g. concurrency limit reached, dependencies not
            satisfied, or executor is shut down).
        """
        if self._shutdown:
            logger.warning("Executor is shut down; rejecting task %s", task_config.task_id)
            return False

        # 节假日二次校验
        from datetime import datetime as dt

        holiday_mode = getattr(task_config, 'holiday_mode', 'none') or 'none'
        if holiday_mode != 'none':
            checker = get_holiday_checker()
            today = dt.now().date()
            if not checker.should_execute(today, holiday_mode):
                logger.info(
                    "Task %s rejected by holiday check: mode=%s, date=%s",
                    task_config.task_id, holiday_mode, today,
                )
                return False

        # Concurrency limit per task
        if not self._check_max_instances(task_config):
            logger.warning(
                "Task %s (%s) rejected: max_instances (%d) reached",
                task_config.task_id,
                task_config.name,
                task_config.max_instances,
            )
            return False

        # Dependency check
        if not self._check_dependencies(task_config):
            logger.warning(
                "Task %s (%s) rejected: dependencies not satisfied",
                task_config.task_id,
                task_config.name,
            )
            return False

        with self._lock:
            heapq.heappush(
                self._priority_queue,
                (task_config.priority, time.monotonic(), task_config),
            )
        logger.info(
            "Task %s (%s) enqueued with priority %d",
            task_config.task_id,
            task_config.name,
            task_config.priority,
        )

        # Attempt to drain the queue immediately.
        self._process_queue()
        return True

    def get_running_tasks(self) -> Dict[str, RunningTaskInfo]:
        """Return a snapshot of currently running tasks.

        Returns:
            A dict mapping *task_id* to ``RunningTaskInfo``.
        """
        with self._lock:
            return dict(self._running_tasks)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task by killing its subprocess.

        Parameters:
            task_id: UUID of the task to cancel.

        Returns:
            ``True`` if the task was found and a kill signal was sent,
            ``False`` otherwise.
        """
        with self._lock:
            info = self._running_tasks.get(task_id)

        if info is None:
            logger.warning("Cannot cancel task %s: not currently running", task_id)
            return False

        if info.process and info.process.poll() is None:
            logger.info("Killing process for task %s (pid=%d)", task_id, info.process.pid)
            try:
                _kill_process(info.process)
            except Exception:
                logger.exception("Error killing process for task %s", task_id)
                return False
            return True

        logger.warning("Task %s process already terminated", task_id)
        return False

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the executor and the underlying thread pool.

        Parameters:
            wait: If ``True``, wait for running tasks to finish.
        """
        logger.info("Shutting down TaskExecutor (wait=%s)", wait)
        self._shutdown = True
        self._thread_pool.shutdown(wait=wait)
        logger.info("TaskExecutor shut down complete")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_max_instances(self, task_config: TaskConfig) -> bool:
        """Return ``True`` if adding one more instance would not exceed
        ``task_config.max_instances``.
        """
        with self._lock:
            running_count = sum(
                1
                for info in self._running_tasks.values()
                if info.task_id == task_config.task_id
            )
        return running_count < task_config.max_instances

    def _check_dependencies(self, task_config: TaskConfig) -> bool:
        """Verify that all dependency tasks have completed successfully.

        Checks the latest ``TaskExecution`` for each dependency; all must
        have ``status == 'success'``.

        Parameters:
            task_config: The task whose dependencies should be checked.

        Returns:
            ``True`` if all dependencies are satisfied (or if there are
            none), ``False`` otherwise.
        """
        if not task_config.dependencies:
            return True

        if self._db is None:
            logger.warning(
                "Cannot check dependencies for task %s: no DatabaseManager",
                task_config.task_id,
            )
            return True  # permissive when DB is unavailable

        for dep_id in task_config.dependencies:
            latest = self._db.get_latest_execution(dep_id)
            if latest is None or latest.status != "success":
                logger.debug(
                    "Dependency %s not satisfied for task %s",
                    dep_id,
                    task_config.task_id,
                )
                return False
        return True

    def _process_queue(self) -> None:
        """Drain the priority queue, dispatching tasks to the thread pool
        as semaphore permits allow.
        """
        while True:
            with self._lock:
                if not self._priority_queue:
                    break

            if not self._semaphore.acquire(blocking=False):
                break  # no more worker slots available

            with self._lock:
                if not self._priority_queue:
                    self._semaphore.release()
                    break
                _priority, _ts, task_config = heapq.heappop(self._priority_queue)

            future = self._thread_pool.submit(self._execute_task, task_config)

            with self._lock:
                self._running_tasks[task_config.task_id] = RunningTaskInfo(
                    task_id=task_config.task_id,
                    task_config=task_config,
                    process=None,
                    start_time=datetime.now(),
                    thread_future=future,
                )

    def _execute_task(self, task_config: TaskConfig) -> None:
        """Execute a task script in a subprocess.

        This method runs in a worker thread.  It:

        1. Optionally records a ``TaskExecution`` in the database.
        2. Invokes the ``on_task_start`` callback.
        3. Spawns the script via ``subprocess.Popen``.
        4. Waits up to ``task_config.timeout`` seconds.
        5. Captures stdout / stderr and return code.
        6. Invokes the ``on_task_complete`` callback.
        7. Updates the database execution record.
        8. Releases the semaphore so the next queued task can run.

        Parameters:
            task_config: The task to execute.
        """
        task_id = task_config.task_id
        execution: Optional[TaskExecution] = None
        start_time = datetime.now()
        success = False
        result: Any = None

        try:
            # on_task_start hook (tracker handles DB recording when bound)
            if self.on_task_start is not None:
                try:
                    self.on_task_start(task_id, task_config)
                except Exception:
                    logger.exception("on_task_start hook failed for task %s", task_id)
            elif self._record_to_db and self._db is not None:
                # Fallback: record execution start in DB when no tracker is bound.
                execution = TaskExecution(
                    task_id=task_id,
                    status="running",
                    start_time=start_time,
                )
                self._db.add_execution(execution)

            # Determine Python interpreter.
            python_exe = _resolve_python(task_config.venv_path)

            logger.info(
                "Starting task %s (%s): %s %s",
                task_id,
                task_config.name,
                python_exe,
                task_config.script_path,
            )

            proc = subprocess.Popen(
                [python_exe, task_config.script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Store process handle so ``cancel_task`` can reach it.
            with self._lock:
                if task_id in self._running_tasks:
                    self._running_tasks[task_id].process = proc

            try:
                stdout, stderr = proc.communicate(timeout=task_config.timeout)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Task %s timed out after %ds – killing", task_id, task_config.timeout
                )
                _kill_process(proc)
                stdout, stderr = proc.communicate()

            return_code = proc.returncode
            success = return_code == 0
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            result = {
                "return_code": return_code,
                "stdout": stdout,
                "stderr": stderr,
                "duration": duration,
            }

            if success:
                logger.info(
                    "Task %s completed successfully in %.2fs", task_id, duration
                )
            else:
                logger.error(
                    "Task %s failed with return_code=%d in %.2fs",
                    task_id,
                    return_code,
                    duration,
                )

            # Update DB execution record (only when no tracker is bound).
            if self.on_task_complete is None and self._record_to_db and self._db is not None and execution is not None:
                self._db.update_execution(
                    execution.id,
                    status="success" if success else "failed",
                    end_time=end_time,
                    duration=duration,
                    return_code=return_code,
                    output=(stdout or "")[:10000],
                    error=(stderr or "")[:10000],
                )

        except Exception:
            logger.exception("Unexpected error executing task %s", task_id)
            success = False
            result = None

            if self.on_task_complete is None and self._record_to_db and self._db is not None:
                try:
                    if execution is not None:
                        self._db.update_execution(
                            execution.id,
                            status="failed",
                            end_time=datetime.now(),
                            duration=(datetime.now() - start_time).total_seconds(),
                            error="Unexpected executor error",
                        )
                    else:
                        self._db.add_execution(
                            TaskExecution(
                                task_id=task_id,
                                status="failed",
                                start_time=start_time,
                                end_time=datetime.now(),
                                duration=(datetime.now() - start_time).total_seconds(),
                                error="Unexpected executor error",
                            )
                        )
                except Exception:
                    logger.exception("Failed to record error execution for task %s", task_id)

        finally:
            # Clean up running-tasks map and release semaphore.
            with self._lock:
                self._running_tasks.pop(task_id, None)
            self._semaphore.release()

            # on_task_complete hook
            if self.on_task_complete is not None:
                try:
                    self.on_task_complete(task_id, success, result)
                except Exception:
                    logger.exception("on_task_complete hook failed for task %s", task_id)

            # Try to drain more queued tasks.
            self._process_queue()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _resolve_python(venv_path: str = "") -> str:
    """Return the path to the Python interpreter.

    If *venv_path* is provided, the interpreter inside that virtual
    environment is returned; otherwise ``sys.executable`` is used.

    Parameters:
        venv_path: Optional path to a virtual environment root.

    Returns:
        Absolute path to a Python executable.
    """
    if venv_path:
        venv_path = os.path.expanduser(venv_path)
        if sys.platform == "win32":
            candidate = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            candidate = os.path.join(venv_path, "bin", "python")
        if os.path.isfile(candidate):
            return candidate
        logger.warning(
            "venv python not found at %s; falling back to sys.executable",
            candidate,
        )
    return sys.executable


def _kill_process(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Terminate a subprocess, escalating to SIGKILL if necessary.

    Parameters:
        proc: The ``Popen`` instance to kill.
    """
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if sys.platform != "win32":
                proc.send_signal(signal.SIGKILL)
            else:
                proc.kill()
            proc.wait(timeout=5)
    except ProcessLookupError:
        pass  # already dead
