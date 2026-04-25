"""Scheduler manager wrapping APScheduler's ``BackgroundScheduler``.

Provides ``SchedulerManager`` which coordinates task lifecycle (add, remove,
update, pause, resume, run-now) and delegates actual execution to a
``TaskExecutor``.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from croncopilot.config.schema import AppConfig
from croncopilot.core.executor import TaskExecutor
from croncopilot.core.holiday import get_holiday_checker
from croncopilot.core.task import (
    TaskConfig,
    parse_schedule,
    record_to_task_config,
    task_config_to_record,
)
from croncopilot.logging.logger import get_logger
from croncopilot.storage.database import DatabaseManager

logger = get_logger(__name__)


class SchedulerManager:
    """High-level scheduler that owns the APScheduler instance and the
    ``TaskExecutor``.

    Parameters:
        config: Application-wide configuration.
        db_manager: Database access layer.
        executor: The ``TaskExecutor`` that actually runs scripts.
    """

    def __init__(
        self,
        config: AppConfig,
        db_manager: DatabaseManager,
        executor: TaskExecutor,
    ) -> None:
        self._config = config
        self._db = db_manager
        self._executor = executor
        self._scheduler = BackgroundScheduler(
            timezone=config.scheduler.timezone,
            job_defaults={
                'misfire_grace_time': None,  # 无论错过多久都补偿执行一次（配合 coalesce）
                'coalesce': True,            # 多次错过的执行合并为一次
                'max_instances': 1,          # 限制同一任务同时只有一个实例
            },
        )
        self._tasks: Dict[str, TaskConfig] = {}
        self._holiday_checker = get_holiday_checker()

        logger.info(
            "SchedulerManager initialised (timezone=%s)", config.scheduler.timezone
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler.

        Loads all enabled tasks from the database, registers them with
        APScheduler, and starts the background scheduler thread.
        """
        self._load_tasks_from_db()
        self._scheduler.start()
        logger.info(
            "Scheduler started with %d task(s)", len(self._tasks)
        )

    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler and the executor.

        Parameters:
            wait: If ``True``, wait for running jobs to finish.
        """
        self._scheduler.shutdown(wait=wait)
        self._executor.shutdown(wait=wait)
        logger.info("Scheduler stopped")

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def add_task(self, task_config: TaskConfig) -> str:
        """Register a new task.

        The task is persisted to the database and, if enabled, scheduled
        in APScheduler.

        Parameters:
            task_config: Configuration for the new task.

        Returns:
            The ``task_id`` of the newly created task.
        """
        # Persist to DB.
        record = task_config_to_record(task_config)
        self._db.add_task(record)

        self._tasks[task_config.task_id] = task_config

        if task_config.enabled:
            self._add_job(task_config)

        logger.info(
            "Task added: %s (%s)", task_config.task_id, task_config.name
        )
        return task_config.task_id

    def remove_task(self, task_id: str) -> None:
        """Remove a task from the scheduler and the database.

        Parameters:
            task_id: UUID of the task to remove.
        """
        self._remove_job(task_id)
        self._tasks.pop(task_id, None)
        self._db.delete_task(task_id)
        logger.info("Task removed: %s", task_id)

    def update_task(self, task_id: str, **kwargs: object) -> None:
        """Update fields of an existing task.

        The APScheduler job is rescheduled if schedule-related fields
        changed.

        Parameters:
            task_id: UUID of the task to update.
            **kwargs: Field names and new values (must match
                ``TaskConfig`` attribute names).
        """
        task_config = self._tasks.get(task_id)
        if task_config is None:
            logger.warning("update_task: unknown task_id %s", task_id)
            return

        schedule_fields = {"schedule_type", "schedule_expr"}
        needs_reschedule = bool(schedule_fields & set(kwargs))

        for key, value in kwargs.items():
            if hasattr(task_config, key):
                setattr(task_config, key, value)

        # Mirror changes to the DB (map TaskConfig field names to
        # TaskRecord column names where they differ).
        db_kwargs = _task_kwargs_to_record_kwargs(kwargs)
        self._db.update_task(task_id, **db_kwargs)

        if needs_reschedule and task_config.enabled:
            self._remove_job(task_id)
            self._add_job(task_config)

        logger.info("Task updated: %s %s", task_id, list(kwargs.keys()))

    def pause_task(self, task_id: str) -> None:
        """Pause scheduling for a task.

        The task remains registered but will not be triggered until
        ``resume_task`` is called.

        Parameters:
            task_id: UUID of the task to pause.
        """
        try:
            self._scheduler.pause_job(job_id=task_id)
            logger.info("Task paused: %s", task_id)
        except Exception:
            logger.exception("Failed to pause task %s", task_id)

    def resume_task(self, task_id: str) -> None:
        """Resume a previously paused task.

        Parameters:
            task_id: UUID of the task to resume.
        """
        try:
            self._scheduler.resume_job(job_id=task_id)
            logger.info("Task resumed: %s", task_id)
        except Exception:
            logger.exception("Failed to resume task %s", task_id)

    def run_task_now(self, task_id: str) -> None:
        """Trigger an immediate one-off execution of a task.

        The task is submitted directly to the ``TaskExecutor`` without
        waiting for its next scheduled time.

        Parameters:
            task_id: UUID of the task to execute.
        """
        task_config = self._tasks.get(task_id)
        if task_config is None:
            logger.warning("run_task_now: unknown task_id %s", task_id)
            return

        logger.info("Running task immediately: %s (%s)", task_id, task_config.name)
        self._executor.submit(task_config)

    def get_task(self, task_id: str) -> Optional[TaskConfig]:
        """Retrieve a task configuration by its ID.

        Parameters:
            task_id: UUID of the task.

        Returns:
            The ``TaskConfig`` or ``None`` if not found.
        """
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[TaskConfig]:
        """Return all registered task configurations.

        Returns:
            A list of ``TaskConfig`` instances.
        """
        return list(self._tasks.values())

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload_tasks(self) -> None:
        """Reload all tasks from the database.

        Removes all current APScheduler jobs, clears the in-memory task
        map, and re-loads everything from the database.  Useful when
        configuration files are changed externally.
        """
        logger.info("Reloading all tasks from database")

        # Remove existing jobs.
        for task_id in list(self._tasks):
            self._remove_job(task_id)
        self._tasks.clear()

        self._load_tasks_from_db()
        logger.info("Reload complete: %d task(s) loaded", len(self._tasks))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_tasks_from_db(self) -> None:
        """Load all enabled tasks from the database and schedule them."""
        records = self._db.list_tasks()
        for record in records:
            try:
                task_config = record_to_task_config(record)
                self._tasks[task_config.task_id] = task_config
                if task_config.enabled:
                    self._add_job(task_config)
            except Exception:
                logger.exception(
                    "Failed to load/schedule task %s (%s)", record.id, record.name
                )

    def _add_job(self, task_config: TaskConfig) -> None:
        """Register an APScheduler job for *task_config*.

        Parameters:
            task_config: The task to schedule.
        """
        trigger = self._create_trigger(task_config)
        if trigger is None:
            logger.error(
                "Cannot create trigger for task %s (%s); skipping",
                task_config.task_id,
                task_config.name,
            )
            return

        self._scheduler.add_job(
            func=self._task_wrapper,
            trigger=trigger,
            args=[task_config.task_id],
            id=task_config.task_id,
            name=task_config.name,
            replace_existing=True,
            max_instances=task_config.max_instances,
        )
        logger.debug(
            "APScheduler job added: %s (%s)", task_config.task_id, task_config.name
        )

    def _remove_job(self, task_id: str) -> None:
        """Remove an APScheduler job, ignoring errors if it does not exist.

        Parameters:
            task_id: UUID used as the APScheduler job ID.
        """
        try:
            self._scheduler.remove_job(job_id=task_id)
        except Exception:
            pass  # job may not exist

    def _create_trigger(
        self, task_config: TaskConfig
    ) -> CronTrigger | IntervalTrigger | None:
        """Build an APScheduler trigger from a ``TaskConfig``.

        Parameters:
            task_config: Task whose schedule should be converted.

        Returns:
            A ``CronTrigger`` or ``IntervalTrigger``, or ``None`` on
            parse failure.
        """
        try:
            params = parse_schedule(task_config.schedule_type, task_config.schedule_expr)
        except ValueError:
            logger.exception(
                "Invalid schedule for task %s: type=%s expr=%s",
                task_config.task_id,
                task_config.schedule_type,
                task_config.schedule_expr,
            )
            return None

        if task_config.schedule_type == "interval":
            return IntervalTrigger(**params)
        else:
            # cron / daily / weekly / monthly all map to CronTrigger fields.
            return CronTrigger(**params)

    def _task_wrapper(self, task_id: str) -> None:
        """APScheduler job function that delegates to the executor.

        Parameters:
            task_id: UUID of the task to execute.
        """
        task_config = self._tasks.get(task_id)
        if task_config is None:
            logger.error("_task_wrapper: task_id %s not found in memory", task_id)
            return

        if not task_config.enabled:
            logger.debug("Task %s is disabled; skipping execution", task_id)
            return

        # 节假日检查
        from datetime import datetime as dt

        today = dt.now().date()
        holiday_mode = getattr(task_config, 'holiday_mode', 'none') or 'none'
        if not self._holiday_checker.should_execute(today, holiday_mode):
            logger.info(
                "Task %s (%s) skipped due to holiday_mode=%s on %s",
                task_id, task_config.name, holiday_mode, today,
            )
            return

        self._executor.submit(task_config)


# ---------------------------------------------------------------------------
# Internal mapping helpers
# ---------------------------------------------------------------------------


def _task_kwargs_to_record_kwargs(kwargs: dict) -> dict:
    """Map ``TaskConfig`` field names to ``TaskRecord`` column names.

    Parameters:
        kwargs: Keyword arguments using ``TaskConfig`` attribute names.

    Returns:
        A new dict with column names suitable for
        ``DatabaseManager.update_task``.
    """
    import json as _json

    mapping = {
        "schedule_expr": "cron_expression",
    }
    result: dict = {}
    for key, value in kwargs.items():
        col = mapping.get(key, key)
        if col == "dependencies" and isinstance(value, list):
            result[col] = _json.dumps(value)
        else:
            result[col] = value
    return result
