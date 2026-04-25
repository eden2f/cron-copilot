"""恢复模块测试 — RetryManager, HealthChecker, DeadlockDetector."""

import time
import threading
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

from croncopilot.config.schema import RecoveryConfig
from croncopilot.core.executor import TaskExecutor, RunningTaskInfo
from croncopilot.core.task import TaskConfig
from croncopilot.monitor.tracker import ExecutionTracker
from croncopilot.monitor.metrics import MetricsCollector
from croncopilot.recovery.retry import RetryManager
from croncopilot.recovery.health import HealthChecker
from croncopilot.recovery.deadlock import DeadlockDetector
from croncopilot.storage.models import TaskRecord


class TestRetryManager:
    """测试 RetryManager."""

    def _make_retry_manager(self, tmp_db, max_retries=3, retry_delay=0.1, backoff_factor=1.0):
        config = RecoveryConfig(
            max_retries=max_retries,
            retry_delay=retry_delay,
            backoff_factor=backoff_factor,
            task_timeout=3600,
        )
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        tracker = ExecutionTracker(db_manager=tmp_db)
        rm = RetryManager(config=config, executor=executor, db_manager=tmp_db, tracker=tracker)
        return rm, executor

    def test_retry_on_failure(self, tmp_db):
        """任务失败后自动重试."""
        rm, executor = self._make_retry_manager(tmp_db, max_retries=3, retry_delay=0.1)

        task_config = TaskConfig(
            name="retry_test",
            script_path="/tmp/t.py",
            max_retries=3,
        )

        # Mock executor.submit to track calls
        submit_calls = []
        original_submit = executor.submit
        executor.submit = lambda tc: submit_calls.append(tc) or True

        rm.on_task_failed(task_config.task_id, task_config, "error msg")

        # Wait for timer to fire
        time.sleep(0.5)
        assert len(submit_calls) == 1
        assert rm.get_retry_count(task_config.task_id) == 1

        executor.shutdown(wait=False)

    def test_retry_exhausted(self, tmp_db):
        """重试次数耗尽后不再重试."""
        rm, executor = self._make_retry_manager(tmp_db, max_retries=2, retry_delay=0.01)

        task_config = TaskConfig(
            name="exhaust_test",
            script_path="/tmp/t.py",
            max_retries=2,
        )

        submit_calls = []
        executor.submit = lambda tc: submit_calls.append(tc) or True

        # Exhaust retries
        rm.on_task_failed(task_config.task_id, task_config, "error 1")
        time.sleep(0.1)
        rm.on_task_failed(task_config.task_id, task_config, "error 2")
        time.sleep(0.1)

        # Third failure should not retry (already at max)
        rm.on_task_failed(task_config.task_id, task_config, "error 3")
        time.sleep(0.1)

        # After exhaustion, retry count is reset
        assert rm.get_retry_count(task_config.task_id) == 0

        executor.shutdown(wait=False)

    def test_retry_backoff_delay(self, tmp_db):
        """指数退避延迟正确计算."""
        config = RecoveryConfig(
            max_retries=5,
            retry_delay=1.0,
            backoff_factor=2.0,
            task_timeout=3600,
        )
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        rm = RetryManager(config=config, executor=executor, db_manager=tmp_db)

        # The delay formula: retry_delay * (backoff_factor ** current_count)
        # count=0 -> 1.0 * 2^0 = 1.0
        # count=1 -> 1.0 * 2^1 = 2.0
        # count=2 -> 1.0 * 2^2 = 4.0
        # We verify indirectly via _schedule_retry being called with correct delay
        scheduled_delays = []
        original_schedule = rm._schedule_retry

        def mock_schedule(task_config, delay):
            scheduled_delays.append(delay)

        rm._schedule_retry = mock_schedule

        task_config = TaskConfig(name="backoff_test", script_path="/tmp/t.py", max_retries=5)

        rm.on_task_failed(task_config.task_id, task_config, "err")
        assert len(scheduled_delays) == 1
        assert scheduled_delays[0] == pytest.approx(1.0)  # 1.0 * 2^0

        rm.on_task_failed(task_config.task_id, task_config, "err")
        assert len(scheduled_delays) == 2
        assert scheduled_delays[1] == pytest.approx(2.0)  # 1.0 * 2^1

        rm.on_task_failed(task_config.task_id, task_config, "err")
        assert len(scheduled_delays) == 3
        assert scheduled_delays[2] == pytest.approx(4.0)  # 1.0 * 2^2

        executor.shutdown(wait=False)

    def test_rollback_on_final_failure(self, tmp_db):
        """重试耗尽后执行回滚."""
        rm, executor = self._make_retry_manager(tmp_db, max_retries=1, retry_delay=0.01)

        task_config = TaskConfig(
            name="rollback_test",
            script_path="/tmp/t.py",
            max_retries=1,
        )

        rollback_called = threading.Event()

        def rollback_handler():
            rollback_called.set()
            return True

        rm.register_rollback(task_config.task_id, rollback_handler)

        # Mock schedule_retry to not actually retry
        rm._schedule_retry = lambda tc, d: None

        # First fail — retry
        rm.on_task_failed(task_config.task_id, task_config, "err")
        # Second fail — exhausted, should rollback
        rm.on_task_failed(task_config.task_id, task_config, "err")

        assert rollback_called.is_set()
        executor.shutdown(wait=False)

    def test_retry_reset_on_success(self, tmp_db):
        """成功后重置计数."""
        rm, executor = self._make_retry_manager(tmp_db, max_retries=3, retry_delay=0.01)

        task_config = TaskConfig(
            name="reset_test",
            script_path="/tmp/t.py",
            max_retries=3,
        )

        rm._schedule_retry = lambda tc, d: None

        rm.on_task_failed(task_config.task_id, task_config, "err")
        assert rm.get_retry_count(task_config.task_id) == 1

        rm.reset_retry_count(task_config.task_id)
        assert rm.get_retry_count(task_config.task_id) == 0

        executor.shutdown(wait=False)


class TestHealthChecker:
    """测试 HealthChecker."""

    def _make_health_checker(self, tmp_db, cpu=50.0, mem=50.0, disk=50.0,
                              cpu_threshold=90.0, mem_threshold=90.0, disk_threshold=90.0):
        config = RecoveryConfig(
            cpu_threshold=cpu_threshold,
            memory_threshold=mem_threshold,
            disk_threshold=disk_threshold,
            health_check_interval=60,
        )
        metrics = MetricsCollector(db_manager=tmp_db)
        # Mock system metrics
        metrics.get_system_metrics = MagicMock(return_value={
            "cpu_percent": cpu,
            "memory_percent": mem,
            "disk_percent": disk,
            "load_average": 1.0,
        })
        pause_cb = MagicMock()
        resume_cb = MagicMock()
        alert_cb = MagicMock()

        hc = HealthChecker(
            config=config,
            metrics=metrics,
            scheduler_pause_callback=pause_cb,
            scheduler_resume_callback=resume_cb,
            alert_callback=alert_cb,
        )
        return hc, pause_cb, resume_cb, alert_cb

    def test_health_check_healthy(self, tmp_db):
        """系统健康时不暂停."""
        hc, pause_cb, resume_cb, alert_cb = self._make_health_checker(
            tmp_db, cpu=30.0, mem=40.0, disk=50.0,
        )
        result = hc.check_health()
        assert result["healthy"] is True
        assert len(result["issues"]) == 0
        pause_cb.assert_not_called()

    def test_health_check_unhealthy(self, tmp_db):
        """资源超限时暂停调度器."""
        hc, pause_cb, resume_cb, alert_cb = self._make_health_checker(
            tmp_db, cpu=95.0, mem=92.0, disk=50.0,
            cpu_threshold=90.0, mem_threshold=90.0,
        )
        result = hc.check_health()
        assert result["healthy"] is False
        assert len(result["issues"]) > 0
        pause_cb.assert_called_once()
        alert_cb.assert_called_once()

    def test_health_check_recovery(self, tmp_db):
        """资源恢复后恢复调度."""
        hc, pause_cb, resume_cb, alert_cb = self._make_health_checker(
            tmp_db, cpu=95.0, mem=92.0, disk=50.0,
            cpu_threshold=90.0, mem_threshold=90.0,
        )

        # First check — unhealthy, should pause
        hc.check_health()
        pause_cb.assert_called_once()

        # Now simulate recovery — healthy metrics
        hc._metrics.get_system_metrics = MagicMock(return_value={
            "cpu_percent": 30.0,
            "memory_percent": 40.0,
            "disk_percent": 50.0,
            "load_average": 0.5,
        })

        result = hc.check_health()
        assert result["healthy"] is True
        resume_cb.assert_called_once()


class TestDeadlockDetector:
    """测试 DeadlockDetector."""

    def _make_detector(self, tmp_db, running_tasks=None, auto_kill=False):
        config = RecoveryConfig(task_timeout=10)
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)

        if running_tasks is not None:
            executor.get_running_tasks = MagicMock(return_value=running_tasks)

        alert_cb = MagicMock()
        detector = DeadlockDetector(
            config=config,
            executor=executor,
            alert_callback=alert_cb,
        )
        detector.auto_kill = auto_kill
        return detector, executor, alert_cb

    def test_deadlock_detection(self, tmp_db):
        """超时任务被检测到."""
        task_config = TaskConfig(
            name="stuck_task",
            script_path="/tmp/t.py",
            timeout=5,
        )
        running_tasks = {
            task_config.task_id: RunningTaskInfo(
                task_id=task_config.task_id,
                task_config=task_config,
                process=None,
                start_time=datetime.now() - timedelta(seconds=100),
            )
        }

        detector, executor, alert_cb = self._make_detector(tmp_db, running_tasks=running_tasks)
        timed_out = detector.detect()

        assert len(timed_out) == 1
        assert timed_out[0]["task_id"] == task_config.task_id
        assert timed_out[0]["running_time"] > 5
        alert_cb.assert_called_once()

        executor.shutdown(wait=False)

    def test_deadlock_auto_kill(self, tmp_db):
        """auto_kill 模式下超时任务被终止."""
        task_config = TaskConfig(
            name="auto_kill_task",
            script_path="/tmp/t.py",
            timeout=5,
        )
        running_tasks = {
            task_config.task_id: RunningTaskInfo(
                task_id=task_config.task_id,
                task_config=task_config,
                process=None,
                start_time=datetime.now() - timedelta(seconds=100),
            )
        }

        detector, executor, alert_cb = self._make_detector(
            tmp_db, running_tasks=running_tasks, auto_kill=True,
        )
        # Mock cancel_task
        executor.cancel_task = MagicMock(return_value=True)

        timed_out = detector.detect()

        assert len(timed_out) == 1
        assert timed_out[0]["action"] == "killed"
        executor.cancel_task.assert_called_once_with(task_config.task_id)

        executor.shutdown(wait=False)

    def test_deadlock_manual_kill(self, tmp_db):
        """手动终止疑似死锁任务."""
        task_config = TaskConfig(
            name="manual_kill_task",
            script_path="/tmp/t.py",
            timeout=5,
        )

        detector, executor, alert_cb = self._make_detector(tmp_db)
        executor.cancel_task = MagicMock(return_value=True)

        result = detector.force_kill(task_config.task_id)
        assert result is True
        executor.cancel_task.assert_called_once_with(task_config.task_id)

        executor.shutdown(wait=False)
