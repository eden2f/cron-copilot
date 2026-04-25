"""Performance metrics collection for CronCopilot tasks.

Provides system-level and per-task metrics using *psutil* as well as
statistical aggregation over historical execution records.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from croncopilot.logging.logger import get_logger
from croncopilot.storage.database import DatabaseManager
from croncopilot.storage.models import TaskExecution

logger = get_logger(__name__)

try:
    import psutil  # type: ignore[import-untyped]

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False
    logger.warning("psutil is not installed; process/system metrics will be unavailable")


class MetricsCollector:
    """Collect runtime metrics for individual processes and the system.

    Parameters:
        db_manager: The database manager used to query execution history.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db: DatabaseManager = db_manager

    # ------------------------------------------------------------------
    # Process-level metrics
    # ------------------------------------------------------------------

    def collect_process_metrics(self, pid: int) -> Dict[str, float]:
        """Collect real-time resource metrics for a running process.

        Uses :mod:`psutil` to sample CPU and memory usage.  If the
        process no longer exists or *psutil* is not installed, empty
        metrics (``0.0``) are returned.

        Parameters:
            pid: Operating-system process ID.

        Returns:
            Dict with keys ``cpu_usage`` (percent) and ``memory_usage``
            (megabytes).
        """
        if not _HAS_PSUTIL:
            logger.debug("psutil unavailable; returning empty process metrics")
            return {"cpu_usage": 0.0, "memory_usage": 0.0}

        try:
            proc = psutil.Process(pid)
            cpu_percent: float = proc.cpu_percent(interval=0.1)
            memory_mb: float = proc.memory_info().rss / (1024 * 1024)
            return {"cpu_usage": round(cpu_percent, 2), "memory_usage": round(memory_mb, 2)}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            logger.debug("Process %d not accessible; returning empty metrics", pid)
            return {"cpu_usage": 0.0, "memory_usage": 0.0}
        except Exception:
            logger.exception("Unexpected error collecting metrics for pid %d", pid)
            return {"cpu_usage": 0.0, "memory_usage": 0.0}

    # ------------------------------------------------------------------
    # Task statistics
    # ------------------------------------------------------------------

    def get_task_stats(self, task_id: str, days: int = 7) -> Dict[str, object]:
        """Compute aggregate statistics for a task over the last *days* days.

        Queries :class:`TaskExecution` records and calculates counts,
        success rate, duration percentiles, and average resource usage.

        Parameters:
            task_id: Unique task identifier.
            days: Number of days to look back.

        Returns:
            Dict containing ``total_runs``, ``success_count``,
            ``failure_count``, ``success_rate``, ``avg_duration``,
            ``max_duration``, ``min_duration``, ``p95_duration``,
            ``avg_cpu_usage``, ``avg_memory_usage``, ``last_run_time``,
            and ``last_status``.
        """
        try:
            # Fetch a generous amount; filter by date in Python for portability.
            executions = self._db.list_executions(task_id, limit=10000)
            cutoff = datetime.now() - timedelta(days=days)
            recent: List[TaskExecution] = [
                e for e in executions
                if e.start_time is not None and e.start_time >= cutoff
                and e.status in ("success", "failed")
            ]

            if not recent:
                return self._empty_stats()

            total = len(recent)
            successes = sum(1 for e in recent if e.status == "success")
            failures = total - successes

            durations = [e.duration for e in recent if e.duration is not None]
            cpu_values = [e.cpu_usage for e in recent if e.cpu_usage is not None]
            mem_values = [e.memory_usage for e in recent if e.memory_usage is not None]

            stats: Dict[str, object] = {
                "total_runs": total,
                "success_count": successes,
                "failure_count": failures,
                "success_rate": round(successes / total * 100, 2) if total else 0.0,
                "avg_duration": round(sum(durations) / len(durations), 3) if durations else 0.0,
                "max_duration": round(max(durations), 3) if durations else 0.0,
                "min_duration": round(min(durations), 3) if durations else 0.0,
                "p95_duration": round(self._percentile(durations, 95), 3) if durations else 0.0,
                "avg_cpu_usage": round(sum(cpu_values) / len(cpu_values), 2) if cpu_values else 0.0,
                "avg_memory_usage": round(sum(mem_values) / len(mem_values), 2) if mem_values else 0.0,
                "last_run_time": recent[0].start_time,
                "last_status": recent[0].status,
            }
            return stats

        except Exception:
            logger.exception("Failed to compute stats for task %s", task_id)
            return self._empty_stats()

    # ------------------------------------------------------------------
    # System-level metrics
    # ------------------------------------------------------------------

    def get_system_metrics(self) -> Dict[str, Optional[float]]:
        """Return current system resource utilisation.

        Uses :mod:`psutil` to sample CPU, memory, and disk usage as well
        as the 1-minute load average (Unix only).

        Returns:
            Dict with ``cpu_percent``, ``memory_percent``,
            ``disk_percent``, and ``load_average``.
        """
        if not _HAS_PSUTIL:
            logger.debug("psutil unavailable; returning empty system metrics")
            return {
                "cpu_percent": None,
                "memory_percent": None,
                "disk_percent": None,
                "load_average": None,
            }

        try:
            cpu_percent: float = psutil.cpu_percent(interval=0.5)
            memory_percent: float = psutil.virtual_memory().percent
            disk_percent: float = psutil.disk_usage("/").percent

            load_average: Optional[float] = None
            try:
                load_average = psutil.getloadavg()[0]  # 1-minute average
            except (AttributeError, OSError):
                pass  # Not available on Windows

            return {
                "cpu_percent": round(cpu_percent, 2),
                "memory_percent": round(memory_percent, 2),
                "disk_percent": round(disk_percent, 2),
                "load_average": round(load_average, 2) if load_average is not None else None,
            }
        except Exception:
            logger.exception("Failed to collect system metrics")
            return {
                "cpu_percent": None,
                "memory_percent": None,
                "disk_percent": None,
                "load_average": None,
            }

    # ------------------------------------------------------------------
    # Threshold checking
    # ------------------------------------------------------------------

    def check_performance_threshold(
        self,
        task_id: str,
        duration_threshold: Optional[float] = None,
        memory_threshold: Optional[float] = None,
    ) -> List[str]:
        """Check whether the most recent execution exceeds performance limits.

        Parameters:
            task_id: Unique task identifier.
            duration_threshold: Maximum acceptable duration in seconds.
            memory_threshold: Maximum acceptable memory usage in MB.

        Returns:
            A list of human-readable warning messages.  An empty list means
            all thresholds were respected.
        """
        warnings: List[str] = []

        try:
            latest = self._db.get_latest_execution(task_id)
            if latest is None:
                return warnings

            if duration_threshold is not None and latest.duration is not None:
                if latest.duration > duration_threshold:
                    warnings.append(
                        f"Task {task_id} duration ({latest.duration:.2f}s) "
                        f"exceeded threshold ({duration_threshold:.2f}s)"
                    )

            if memory_threshold is not None and latest.memory_usage is not None:
                if latest.memory_usage > memory_threshold:
                    warnings.append(
                        f"Task {task_id} memory usage ({latest.memory_usage:.2f}MB) "
                        f"exceeded threshold ({memory_threshold:.2f}MB)"
                    )

        except Exception:
            logger.exception("Failed to check performance thresholds for task %s", task_id)

        return warnings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _percentile(data: List[float], pct: float) -> float:
        """Compute the *pct*-th percentile of a sorted list of values.

        Parameters:
            data: Non-empty list of numeric values.
            pct: Percentile in ``[0, 100]``.

        Returns:
            The interpolated percentile value.
        """
        sorted_data = sorted(data)
        n = len(sorted_data)
        if n == 1:
            return sorted_data[0]
        k = (pct / 100.0) * (n - 1)
        lower = int(k)
        upper = lower + 1
        if upper >= n:
            return sorted_data[-1]
        weight = k - lower
        return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight

    @staticmethod
    def _empty_stats() -> Dict[str, object]:
        """Return a stats dict with zeroed values."""
        return {
            "total_runs": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0.0,
            "avg_duration": 0.0,
            "max_duration": 0.0,
            "min_duration": 0.0,
            "p95_duration": 0.0,
            "avg_cpu_usage": 0.0,
            "avg_memory_usage": 0.0,
            "last_run_time": None,
            "last_status": None,
        }
