"""Multi-channel alert system for PyCronGuard.

Provides pluggable alert strategies (immediate failure, consecutive failure,
performance threshold) and notification channels (email).  The
:class:`AlertManager` orchestrates strategy evaluation, cooldown enforcement,
and delivery logging.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Tuple

from pycronguard.config.schema import AlertConfig, AlertEmailConfig
from pycronguard.logging.logger import get_logger
from pycronguard.monitor.metrics import MetricsCollector
from pycronguard.monitor.tracker import ExecutionTracker
from pycronguard.storage.database import DatabaseManager
from pycronguard.storage.models import AlertLog, TaskExecution

logger = get_logger(__name__)


# ======================================================================
# Notifiers
# ======================================================================


class EmailNotifier:
    """Send alert notifications via SMTP email.

    Parameters:
        config: Email channel configuration.
    """

    def __init__(self, config: AlertEmailConfig) -> None:
        self._config: AlertEmailConfig = config

    def send(self, subject: str, body: str, recipients: Optional[List[str]] = None) -> bool:
        """Send an email message.

        Parameters:
            subject: Email subject line.
            body: Plain-text email body.
            recipients: Override recipient list; falls back to the
                configured recipients.

        Returns:
            ``True`` if the email was sent successfully, ``False`` otherwise.
        """
        target_recipients = recipients or self._config.recipients
        if not target_recipients:
            logger.warning("EmailNotifier: no recipients configured; skipping send")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self._config.sender or self._config.username
            msg["To"] = ", ".join(target_recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if self._config.use_tls:
                server = smtplib.SMTP(self._config.smtp_host, self._config.smtp_port)
                server.ehlo()
                server.starttls()
            else:
                # Non-TLS or implicit SSL on port 465.
                if self._config.smtp_port == 465:
                    server = smtplib.SMTP_SSL(self._config.smtp_host, self._config.smtp_port)
                else:
                    server = smtplib.SMTP(self._config.smtp_host, self._config.smtp_port)

            try:
                if self._config.username and self._config.password:
                    server.login(self._config.username, self._config.password)
                server.sendmail(
                    msg["From"],
                    target_recipients,
                    msg.as_string(),
                )
                logger.info("EmailNotifier: sent alert to %s", target_recipients)
                return True
            finally:
                server.quit()

        except Exception:
            logger.exception("EmailNotifier: failed to send email")
            return False


# ======================================================================
# Alert strategies
# ======================================================================


class AlertStrategy:
    """Base class for alert strategies.

    Subclasses implement :meth:`should_alert` to decide whether a given
    execution warrants an alert.
    """

    def should_alert(
        self,
        task_id: str,
        execution: TaskExecution,
        tracker: ExecutionTracker,
    ) -> Tuple[bool, str]:
        """Evaluate whether an alert should be raised.

        Parameters:
            task_id: Unique task identifier.
            execution: The execution record to evaluate.
            tracker: The execution tracker for querying history.

        Returns:
            A ``(should_alert, message)`` tuple.
        """
        raise NotImplementedError


class ImmediateFailureStrategy(AlertStrategy):
    """Raise an alert immediately when a task execution fails."""

    def should_alert(
        self,
        task_id: str,
        execution: TaskExecution,
        tracker: ExecutionTracker,
    ) -> Tuple[bool, str]:
        if execution.status == "failed":
            message = (
                f"[Immediate Failure] Task {task_id} failed.\n"
                f"Return code: {execution.return_code}\n"
                f"Error: {(execution.error or 'N/A')[:500]}"
            )
            return True, message
        return False, ""


class ConsecutiveFailureStrategy(AlertStrategy):
    """Raise an alert when a task has failed *threshold* times in a row.

    Parameters:
        threshold: Minimum number of consecutive failures to trigger.
    """

    def __init__(self, threshold: int = 3) -> None:
        self._threshold: int = threshold

    def should_alert(
        self,
        task_id: str,
        execution: TaskExecution,
        tracker: ExecutionTracker,
    ) -> Tuple[bool, str]:
        if execution.status != "failed":
            return False, ""

        consecutive = tracker.get_consecutive_failures(task_id)
        if consecutive >= self._threshold:
            message = (
                f"[Consecutive Failure] Task {task_id} has failed "
                f"{consecutive} times consecutively (threshold: {self._threshold}).\n"
                f"Latest error: {(execution.error or 'N/A')[:500]}"
            )
            return True, message
        return False, ""


class PerformanceThresholdStrategy(AlertStrategy):
    """Raise an alert when execution duration or memory exceeds limits.

    Parameters:
        duration_threshold: Maximum acceptable duration in seconds.
        memory_threshold: Maximum acceptable memory usage in MB.
        metrics_collector: The metrics collector used to check thresholds.
    """

    def __init__(
        self,
        duration_threshold: Optional[float] = None,
        memory_threshold: Optional[float] = None,
        metrics_collector: Optional[MetricsCollector] = None,
    ) -> None:
        self._duration_threshold: Optional[float] = duration_threshold
        self._memory_threshold: Optional[float] = memory_threshold
        self._metrics: Optional[MetricsCollector] = metrics_collector

    def should_alert(
        self,
        task_id: str,
        execution: TaskExecution,
        tracker: ExecutionTracker,
    ) -> Tuple[bool, str]:
        warnings: List[str] = []

        if self._duration_threshold is not None and execution.duration is not None:
            if execution.duration > self._duration_threshold:
                warnings.append(
                    f"Duration ({execution.duration:.2f}s) exceeded "
                    f"threshold ({self._duration_threshold:.2f}s)"
                )

        if self._memory_threshold is not None and execution.memory_usage is not None:
            if execution.memory_usage > self._memory_threshold:
                warnings.append(
                    f"Memory ({execution.memory_usage:.2f}MB) exceeded "
                    f"threshold ({self._memory_threshold:.2f}MB)"
                )

        if warnings:
            message = (
                f"[Performance Alert] Task {task_id}:\n"
                + "\n".join(f"  - {w}" for w in warnings)
            )
            return True, message

        return False, ""


# ======================================================================
# Alert manager
# ======================================================================


class AlertManager:
    """Orchestrate alert evaluation, delivery, and logging.

    Parameters:
        config: Alert subsystem configuration.
        db_manager: Database manager for persisting alert logs.
        tracker: Execution tracker for querying task history.
        metrics: Metrics collector used by performance strategies.
    """

    def __init__(
        self,
        config: AlertConfig,
        db_manager: DatabaseManager,
        tracker: ExecutionTracker,
        metrics: MetricsCollector,
    ) -> None:
        self._config: AlertConfig = config
        self._db: DatabaseManager = db_manager
        self._tracker: ExecutionTracker = tracker
        self._metrics: MetricsCollector = metrics
        self._notifiers: Dict[str, EmailNotifier] = {}
        self._strategies: List[AlertStrategy] = []
        self._cooldowns: Dict[str, datetime] = {}

        self._setup_notifiers()
        self._setup_strategies()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _setup_notifiers(self) -> None:
        """Initialise notification channels based on configuration."""
        if self._config.email.enabled:
            self._notifiers["email"] = EmailNotifier(self._config.email)
            logger.info("AlertManager: email notifier enabled")

    def _setup_strategies(self) -> None:
        """Initialise alert strategies based on configuration."""
        if self._config.failure_immediate:
            self._strategies.append(ImmediateFailureStrategy())
            logger.info("AlertManager: immediate-failure strategy enabled")

        if self._config.consecutive_failure_threshold > 0:
            self._strategies.append(
                ConsecutiveFailureStrategy(self._config.consecutive_failure_threshold)
            )
            logger.info(
                "AlertManager: consecutive-failure strategy enabled (threshold=%d)",
                self._config.consecutive_failure_threshold,
            )

    # ------------------------------------------------------------------
    # Core alert logic
    # ------------------------------------------------------------------

    def check_and_alert(self, task_id: str, execution: TaskExecution) -> None:
        """Evaluate all strategies and dispatch alerts for the given execution.

        For each strategy that fires:

        1. The cooldown window is checked to avoid alert spam.
        2. Alerts are sent through every configured notifier.
        3. An :class:`AlertLog` is persisted for each delivery attempt.

        Parameters:
            task_id: Unique task identifier.
            execution: The execution record to evaluate.
        """
        for strategy in self._strategies:
            try:
                should_fire, message = strategy.should_alert(task_id, execution, self._tracker)
                if not should_fire:
                    continue

                alert_type = type(strategy).__name__

                if self._is_in_cooldown(task_id, alert_type):
                    logger.debug(
                        "AlertManager: alert %s for task %s is in cooldown; skipping",
                        alert_type,
                        task_id,
                    )
                    continue

                # Update cooldown timestamp.
                cooldown_key = f"{task_id}:{alert_type}"
                self._cooldowns[cooldown_key] = datetime.now()

                # Dispatch through all notifiers.
                subject = f"[PyCronGuard Alert] {alert_type} — Task {task_id}"

                if not self._notifiers:
                    # No notifiers configured; just log.
                    logger.warning("AlertManager: %s — %s", alert_type, message)
                    self._record_alert(task_id, alert_type, "log", message, True)
                    continue

                for channel_name, notifier in self._notifiers.items():
                    try:
                        success = notifier.send(subject, message)
                        self._record_alert(task_id, alert_type, channel_name, message, success)
                    except Exception:
                        logger.exception(
                            "AlertManager: failed to send via %s for task %s",
                            channel_name,
                            task_id,
                        )
                        self._record_alert(task_id, alert_type, channel_name, message, False)

            except Exception:
                logger.exception(
                    "AlertManager: strategy %s raised an error for task %s",
                    type(strategy).__name__,
                    task_id,
                )

    # ------------------------------------------------------------------
    # Cooldown management
    # ------------------------------------------------------------------

    def _is_in_cooldown(self, task_id: str, alert_type: str) -> bool:
        """Return ``True`` if the given alert type for a task is in cooldown.

        Parameters:
            task_id: Unique task identifier.
            alert_type: Strategy class name used as the alert type key.

        Returns:
            Whether the cooldown window has not yet elapsed.
        """
        cooldown_key = f"{task_id}:{alert_type}"
        last_alert = self._cooldowns.get(cooldown_key)
        if last_alert is None:
            return False
        elapsed = (datetime.now() - last_alert).total_seconds()
        return elapsed < self._config.cooldown_seconds

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _record_alert(
        self,
        task_id: str,
        alert_type: str,
        channel: str,
        message: str,
        success: bool,
    ) -> None:
        """Persist an alert log entry.

        Parameters:
            task_id: Unique task identifier.
            alert_type: Strategy class name.
            channel: Notification channel used (e.g. ``"email"``).
            message: The alert message body.
            success: Whether delivery succeeded.
        """
        try:
            log = AlertLog(
                task_id=task_id,
                alert_type=alert_type,
                channel=channel,
                message=message[:5000] if message else None,
                success=success,
            )
            self._db.add_alert_log(log)
            logger.debug(
                "AlertManager: recorded alert log — type=%s channel=%s success=%s",
                alert_type,
                channel,
                success,
            )
        except Exception:
            logger.exception("AlertManager: failed to record alert log for task %s", task_id)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_alert_history(
        self, task_id: Optional[str] = None, limit: int = 50
    ) -> List[AlertLog]:
        """Return recent alert log entries.

        Parameters:
            task_id: If provided, filter by task. Otherwise return all.
            limit: Maximum number of entries to return.

        Returns:
            List of :class:`AlertLog` instances, newest first.
        """
        try:
            return self._db.list_alert_logs(task_id=task_id, limit=limit)
        except Exception:
            logger.exception("AlertManager: failed to fetch alert history")
            return []

    # ------------------------------------------------------------------
    # Tracker binding
    # ------------------------------------------------------------------

    def bind_tracker(self, tracker: ExecutionTracker) -> None:
        """Bind alert checking to the tracker's task-complete event.

        After this call, every time a task completes the tracker will
        automatically invoke :meth:`check_and_alert`.

        Parameters:
            tracker: The execution tracker to bind to.
        """
        tracker._on_complete_callback = self.check_and_alert
        logger.info("AlertManager: bound to ExecutionTracker")
