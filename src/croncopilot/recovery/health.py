"""System health checker for CronCopilot.

Periodically monitors CPU, memory, and disk utilisation against configured
thresholds.  When the system is unhealthy the scheduler can be automatically
paused to prevent overload; it resumes once metrics return to safe levels.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional

from croncopilot.config.schema import RecoveryConfig
from croncopilot.logging.logger import get_logger
from croncopilot.monitor.metrics import MetricsCollector

logger = get_logger(__name__)


class HealthChecker:
    """Periodically check system resource health and react accordingly.

    Parameters:
        config: Recovery subsystem configuration (contains thresholds and
            check interval).
        metrics: Metrics collector used to sample system resources.
        scheduler_pause_callback: Called to pause the scheduler when the
            system is unhealthy.
        scheduler_resume_callback: Called to resume the scheduler when
            health is restored.
        alert_callback: Called with a message string when an unhealthy
            condition is detected.
    """

    def __init__(
        self,
        config: RecoveryConfig,
        metrics: MetricsCollector,
        scheduler_pause_callback: Optional[Callable[[], None]] = None,
        scheduler_resume_callback: Optional[Callable[[], None]] = None,
        alert_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._config: RecoveryConfig = config
        self._metrics: MetricsCollector = metrics
        self._pause_scheduler: Optional[Callable[[], None]] = scheduler_pause_callback
        self._resume_scheduler: Optional[Callable[[], None]] = scheduler_resume_callback
        self._alert: Optional[Callable[[str], None]] = alert_callback
        self._timer: Optional[threading.Timer] = None
        self._running: bool = False
        self._is_paused: bool = False  # Whether the scheduler was paused due to health issues
        self._last_check: Optional[Dict[str, object]] = None
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the periodic health-check loop.

        The first check runs immediately; subsequent checks are scheduled
        at ``config.health_check_interval`` second intervals.
        """
        with self._lock:
            if self._running:
                logger.warning("HealthChecker: already running")
                return
            self._running = True
        logger.info(
            "HealthChecker: started (interval=%ds)",
            self._config.health_check_interval,
        )
        self._check_loop()

    def stop(self) -> None:
        """Stop the periodic health-check loop."""
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        logger.info("HealthChecker: stopped")

    # ------------------------------------------------------------------
    # Internal scheduling
    # ------------------------------------------------------------------

    def _check_loop(self) -> None:
        """Execute one check and schedule the next iteration."""
        with self._lock:
            if not self._running:
                return

        self.check_health()

        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(
                self._config.health_check_interval,
                self._check_loop,
            )
            self._timer.daemon = True
            self._timer.start()

    # ------------------------------------------------------------------
    # Core health check
    # ------------------------------------------------------------------

    def check_health(self) -> Dict[str, object]:
        """Perform a single health check against configured thresholds.

        Checks:
        - CPU usage vs ``cpu_threshold``
        - Memory usage vs ``memory_threshold``
        - Disk usage vs ``disk_threshold``

        Side effects:
        - Logs warnings for each breached threshold.
        - Sends an alert via ``alert_callback`` if any threshold is breached.
        - Pauses the scheduler (via ``scheduler_pause_callback``) when the
          system becomes unhealthy.
        - Resumes the scheduler when the system returns to healthy state
          after being paused.

        Returns:
            A dict with keys ``healthy`` (bool), ``issues`` (list of str),
            and ``metrics`` (dict of raw metric values).
        """
        sys_metrics = self._metrics.get_system_metrics()
        issues: List[str] = []

        cpu = sys_metrics.get("cpu_percent")
        mem = sys_metrics.get("memory_percent")
        disk = sys_metrics.get("disk_percent")

        if cpu is not None and cpu > self._config.cpu_threshold:
            issues.append(
                f"CPU usage {cpu:.1f}% exceeds threshold {self._config.cpu_threshold:.1f}%"
            )

        if mem is not None and mem > self._config.memory_threshold:
            issues.append(
                f"Memory usage {mem:.1f}% exceeds threshold {self._config.memory_threshold:.1f}%"
            )

        if disk is not None and disk > self._config.disk_threshold:
            issues.append(
                f"Disk usage {disk:.1f}% exceeds threshold {self._config.disk_threshold:.1f}%"
            )

        healthy = len(issues) == 0

        result: Dict[str, object] = {
            "healthy": healthy,
            "issues": issues,
            "metrics": sys_metrics,
        }

        with self._lock:
            self._last_check = result

        if not healthy:
            # Log each issue.
            for issue in issues:
                logger.warning("HealthChecker: %s", issue)

            # Send alert.
            if self._alert is not None:
                alert_msg = (
                    "[Health Alert] System resource thresholds breached:\n"
                    + "\n".join(f"  - {i}" for i in issues)
                )
                try:
                    self._alert(alert_msg)
                except Exception:
                    logger.exception("HealthChecker: alert callback raised")

            # Pause scheduler if not already paused.
            with self._lock:
                was_paused = self._is_paused
            if not was_paused:
                with self._lock:
                    self._is_paused = True
                if self._pause_scheduler is not None:
                    try:
                        self._pause_scheduler()
                        logger.warning(
                            "HealthChecker: scheduler paused due to unhealthy system"
                        )
                    except Exception:
                        logger.exception("HealthChecker: pause_scheduler callback raised")
        else:
            # System is healthy — resume if previously paused.
            with self._lock:
                was_paused = self._is_paused
            if was_paused:
                with self._lock:
                    self._is_paused = False
                if self._resume_scheduler is not None:
                    try:
                        self._resume_scheduler()
                        logger.info(
                            "HealthChecker: scheduler resumed — system healthy again"
                        )
                    except Exception:
                        logger.exception("HealthChecker: resume_scheduler callback raised")

        return result

    # ------------------------------------------------------------------
    # Status query
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, object]:
        """Return a summary of the health checker's current state.

        Returns:
            Dict with ``running`` (bool), ``is_paused`` (bool), and
            ``last_check`` (dict or ``None``).
        """
        with self._lock:
            return {
                "running": self._running,
                "is_paused": self._is_paused,
                "last_check": self._last_check,
            }
