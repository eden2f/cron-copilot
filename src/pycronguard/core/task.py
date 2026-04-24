"""Task data model and schedule parsing utilities.

Defines ``TaskConfig`` — the in-memory representation of a scheduled task —
together with helpers that convert between ``TaskConfig`` and the database
``TaskRecord`` model and that translate human-friendly schedule expressions
into APScheduler trigger parameters.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

from pycronguard.logging.logger import get_logger
from pycronguard.storage.models import TaskRecord

logger = get_logger(__name__)


@dataclass
class TaskConfig:
    """In-memory task configuration.

    Attributes:
        task_id: Unique task identifier (UUID).
        name: Human-readable task name.
        script_path: Filesystem path to the script to execute.
        schedule_type: One of ``cron``, ``daily``, ``weekly``, ``monthly``,
            ``interval``.
        schedule_expr: Schedule expression whose format depends on
            *schedule_type*.
        priority: Execution priority; 1 (highest) – 10 (lowest).
        max_retries: Maximum retry attempts on failure.
        timeout: Execution timeout in seconds.
        dependencies: List of *task_id* values this task depends on.
        enabled: Whether the task is active.
        category: Optional grouping label.
        description: Optional free-text description.
        venv_path: Optional path to a Python virtual environment.
        max_instances: Maximum concurrent instances of this task.
    """

    task_id: str = ""
    name: str = ""
    script_path: str = ""
    schedule_type: str = "cron"
    schedule_expr: str = ""
    priority: int = 5
    max_retries: int = 3
    timeout: int = 3600
    dependencies: List[str] = field(default_factory=list)
    enabled: bool = True
    category: str = ""
    description: str = ""
    venv_path: str = ""
    max_instances: int = 1

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schedule parsing
# ---------------------------------------------------------------------------

# Regex for interval expressions like "30m", "2h", "1d", "90s"
_INTERVAL_RE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)

_DAY_OF_WEEK_NAMES = {
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
}


def parse_schedule(schedule_type: str, schedule_expr: str) -> Dict[str, Any]:
    """Convert a human-friendly schedule expression into APScheduler trigger
    keyword arguments.

    Parameters:
        schedule_type: One of ``cron``, ``daily``, ``weekly``, ``monthly``,
            ``interval``.
        schedule_expr: The expression string matching *schedule_type*.

    Returns:
        A dict of keyword arguments suitable for constructing the
        corresponding APScheduler trigger.

    Raises:
        ValueError: If *schedule_type* is unknown or *schedule_expr* cannot
            be parsed.

    Examples:
        >>> parse_schedule("cron", "0 8 * * *")
        {'minute': '0', 'hour': '8', 'day': '*', 'month': '*', 'day_of_week': '*'}
        >>> parse_schedule("daily", "08:00")
        {'hour': 8, 'minute': 0}
        >>> parse_schedule("weekly", "mon@08:00")
        {'day_of_week': 'mon', 'hour': 8, 'minute': 0}
        >>> parse_schedule("monthly", "1@08:00")
        {'day': 1, 'hour': 8, 'minute': 0}
        >>> parse_schedule("interval", "30m")
        {'minutes': 30}
    """

    schedule_type = schedule_type.strip().lower()
    schedule_expr = schedule_expr.strip()

    if schedule_type == "cron":
        return _parse_cron(schedule_expr)
    elif schedule_type == "daily":
        return _parse_daily(schedule_expr)
    elif schedule_type == "weekly":
        return _parse_weekly(schedule_expr)
    elif schedule_type == "monthly":
        return _parse_monthly(schedule_expr)
    elif schedule_type == "interval":
        return _parse_interval(schedule_expr)
    else:
        raise ValueError(f"Unknown schedule_type: {schedule_type!r}")


def _parse_cron(expr: str) -> Dict[str, Any]:
    """Parse a standard 5-field cron expression.

    Fields: minute hour day month day_of_week.
    """
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(
            f"Cron expression must have exactly 5 fields, got {len(parts)}: {expr!r}"
        )
    minute, hour, day, month, day_of_week = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


def _parse_daily(expr: str) -> Dict[str, int]:
    """Parse a daily expression like ``HH:MM``."""
    try:
        hour_s, minute_s = expr.split(":")
        hour = int(hour_s)
        minute = int(minute_s)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid daily expression: {expr!r}") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Hour/minute out of range in daily expression: {expr!r}")
    return {"hour": hour, "minute": minute}


def _parse_weekly(expr: str) -> Dict[str, Any]:
    """Parse a weekly expression like ``mon@08:00``."""
    if "@" not in expr:
        raise ValueError(f"Weekly expression must contain '@': {expr!r}")

    day_part, time_part = expr.split("@", maxsplit=1)
    day_part = day_part.strip().lower()
    if day_part not in _DAY_OF_WEEK_NAMES:
        raise ValueError(f"Unknown day of week: {day_part!r}")

    time_kwargs = _parse_daily(time_part.strip())
    return {"day_of_week": day_part, **time_kwargs}


def _parse_monthly(expr: str) -> Dict[str, Any]:
    """Parse a monthly expression like ``1@08:00``."""
    if "@" not in expr:
        raise ValueError(f"Monthly expression must contain '@': {expr!r}")

    day_part, time_part = expr.split("@", maxsplit=1)
    try:
        day = int(day_part.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid day in monthly expression: {day_part!r}") from exc

    if not (1 <= day <= 31):
        raise ValueError(f"Day out of range in monthly expression: {day}")

    time_kwargs = _parse_daily(time_part.strip())
    return {"day": day, **time_kwargs}


def _parse_interval(expr: str) -> Dict[str, int]:
    """Parse an interval expression like ``30m``, ``2h``, ``1d``, ``90s``."""
    match = _INTERVAL_RE.match(expr)
    if not match:
        raise ValueError(f"Invalid interval expression: {expr!r}")

    value = int(match.group(1))
    unit = match.group(2).lower()

    unit_map = {
        "s": "seconds",
        "m": "minutes",
        "h": "hours",
        "d": "days",
    }
    return {unit_map[unit]: value}


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def task_config_to_record(config: TaskConfig) -> TaskRecord:
    """Convert a ``TaskConfig`` instance to a ``TaskRecord`` ORM object.

    Parameters:
        config: The in-memory task configuration.

    Returns:
        A detached ``TaskRecord`` ready to be persisted.
    """
    dependencies_json: str | None = None
    if config.dependencies:
        dependencies_json = json.dumps(config.dependencies)

    record = TaskRecord(
        id=config.task_id,
        name=config.name,
        script_path=config.script_path,
        cron_expression=config.schedule_expr,
        schedule_type=config.schedule_type,
        priority=config.priority,
        max_retries=config.max_retries,
        timeout=config.timeout,
        dependencies=dependencies_json,
        enabled=config.enabled,
        category=config.category or None,
        description=config.description or None,
        venv_path=config.venv_path or None,
        max_instances=config.max_instances,
    )
    logger.debug("Converted TaskConfig %s to TaskRecord", config.task_id)
    return record


def record_to_task_config(record: TaskRecord) -> TaskConfig:
    """Restore a ``TaskConfig`` from a ``TaskRecord`` ORM object.

    Parameters:
        record: A database task record.

    Returns:
        The corresponding ``TaskConfig`` instance.
    """
    dependencies: List[str] = []
    if record.dependencies:
        try:
            dependencies = json.loads(record.dependencies)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to parse dependencies JSON for task %s", record.id
            )

    return TaskConfig(
        task_id=record.id,
        name=record.name,
        script_path=record.script_path,
        schedule_type=record.schedule_type or "cron",
        schedule_expr=record.cron_expression or "",
        priority=record.priority,
        max_retries=record.max_retries,
        timeout=record.timeout,
        dependencies=dependencies,
        enabled=record.enabled,
        category=record.category or "",
        description=record.description or "",
        venv_path=record.venv_path or "",
        max_instances=record.max_instances,
    )
