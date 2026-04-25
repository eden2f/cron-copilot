"""监控模块测试 — ExecutionTracker, MetricsCollector, AlertManager."""

import os
import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

from croncopilot.config.schema import AlertConfig, AlertEmailConfig
from croncopilot.core.task import TaskConfig
from croncopilot.monitor.tracker import ExecutionTracker
from croncopilot.monitor.metrics import MetricsCollector
from croncopilot.monitor.alert import (
    AlertManager,
    EmailNotifier,
    ImmediateFailureStrategy,
    ConsecutiveFailureStrategy,
)
from croncopilot.storage.models import TaskExecution, TaskRecord


class TestExecutionTracker:
    """测试 ExecutionTracker."""

    def test_tracker_on_task_start(self, tmp_db):
        """正确创建执行记录."""
        # Create a parent task record first (for FK)
        task_config = TaskConfig(name="track_start", script_path="/tmp/t.py")
        record = TaskRecord(id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py")
        tmp_db.add_task(record)

        tracker = ExecutionTracker(db_manager=tmp_db)
        tracker.on_task_start(task_config.task_id, task_config)

        active = tracker.get_active_executions()
        assert task_config.task_id in active
        assert active[task_config.task_id].status == "running"

    def test_tracker_on_task_complete(self, tmp_db):
        """正确更新执行记录."""
        task_config = TaskConfig(name="track_complete", script_path="/tmp/t.py")
        record = TaskRecord(id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py")
        tmp_db.add_task(record)

        tracker = ExecutionTracker(db_manager=tmp_db)
        tracker.on_task_start(task_config.task_id, task_config)

        result = {
            "return_code": 0,
            "stdout": "output",
            "stderr": "",
            "duration": 1.5,
        }
        execution = tracker.on_task_complete(task_config.task_id, True, result)

        assert execution is not None
        assert execution.status == "success"
        assert execution.duration == 1.5
        # Should no longer be active
        assert task_config.task_id not in tracker.get_active_executions()

    def test_consecutive_failures(self, tmp_db):
        """连续失败计数正确."""
        task_config = TaskConfig(name="consec_fail", script_path="/tmp/t.py")
        record = TaskRecord(id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py")
        tmp_db.add_task(record)

        # Directly add failed execution records to DB (bypassing tracker's
        # on_task_start which adds 'running' records that break the count).
        from datetime import datetime, timedelta
        now = datetime.now()
        for i in range(3):
            exec_rec = TaskExecution(
                task_id=task_config.task_id,
                status="failed",
                start_time=now - timedelta(minutes=3 - i),
                end_time=now - timedelta(minutes=3 - i, seconds=-5),
                duration=5.0,
                return_code=1,
                error=f"error {i}",
            )
            tmp_db.add_execution(exec_rec)

        tracker = ExecutionTracker(db_manager=tmp_db)
        count = tracker.get_consecutive_failures(task_config.task_id)
        assert count == 3

        # Now add a success — consecutive failures should reset
        exec_ok = TaskExecution(
            task_id=task_config.task_id,
            status="success",
            start_time=now,
            end_time=now + timedelta(seconds=1),
            duration=1.0,
            return_code=0,
        )
        tmp_db.add_execution(exec_ok)
        count = tracker.get_consecutive_failures(task_config.task_id)
        assert count == 0


class TestMetricsCollector:
    """测试 MetricsCollector."""

    @patch("croncopilot.monitor.metrics._HAS_PSUTIL", True)
    @patch("croncopilot.monitor.metrics.psutil")
    def test_metrics_system(self, mock_psutil, tmp_db):
        """系统指标采集（CPU/内存/磁盘）."""
        mock_psutil.cpu_percent.return_value = 45.0
        mock_psutil.virtual_memory.return_value = MagicMock(percent=60.0)
        mock_psutil.disk_usage.return_value = MagicMock(percent=70.0)
        mock_psutil.getloadavg.return_value = (1.5, 1.2, 0.8)

        collector = MetricsCollector(db_manager=tmp_db)
        metrics = collector.get_system_metrics()

        assert metrics["cpu_percent"] == 45.0
        assert metrics["memory_percent"] == 60.0
        assert metrics["disk_percent"] == 70.0
        assert metrics["load_average"] == 1.5

    def test_metrics_task_stats(self, tmp_db):
        """任务统计计算正确."""
        task_config = TaskConfig(name="stats_task", script_path="/tmp/t.py")
        record = TaskRecord(id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py")
        tmp_db.add_task(record)

        # Add some execution records
        now = datetime.now()
        for i in range(5):
            exec_rec = TaskExecution(
                task_id=task_config.task_id,
                status="success" if i < 3 else "failed",
                start_time=now - timedelta(hours=i),
                end_time=now - timedelta(hours=i) + timedelta(seconds=10 + i),
                duration=10.0 + i,
                return_code=0 if i < 3 else 1,
            )
            tmp_db.add_execution(exec_rec)

        collector = MetricsCollector(db_manager=tmp_db)
        stats = collector.get_task_stats(task_config.task_id, days=7)

        assert stats["total_runs"] == 5
        assert stats["success_count"] == 3
        assert stats["failure_count"] == 2
        assert stats["success_rate"] == 60.0
        assert stats["avg_duration"] > 0
        assert stats["max_duration"] >= stats["min_duration"]


class TestEmailNotifier:
    """测试 EmailNotifier."""

    @patch("croncopilot.monitor.alert.smtplib.SMTP")
    def test_email_notifier(self, mock_smtp_cls):
        """EmailNotifier（mock SMTP）."""
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        config = AlertEmailConfig(
            enabled=True,
            smtp_host="smtp.test.com",
            smtp_port=587,
            use_tls=True,
            username="user@test.com",
            password="pass",
            sender="noreply@test.com",
            recipients=["admin@test.com"],
        )
        notifier = EmailNotifier(config)
        result = notifier.send("Test Subject", "Test Body")

        assert result is True
        mock_server.ehlo.assert_called_once()
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@test.com", "pass")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()


class TestAlertStrategies:
    """测试告警策略."""

    def test_immediate_failure_strategy(self, tmp_db):
        """失败立即触发告警."""
        tracker = ExecutionTracker(db_manager=tmp_db)
        strategy = ImmediateFailureStrategy()

        # Failed execution
        execution = TaskExecution(
            task_id="task-1",
            status="failed",
            return_code=1,
            error="something went wrong",
        )
        should, msg = strategy.should_alert("task-1", execution, tracker)
        assert should is True
        assert "Immediate Failure" in msg

        # Successful execution
        execution_ok = TaskExecution(
            task_id="task-1",
            status="success",
            return_code=0,
        )
        should, msg = strategy.should_alert("task-1", execution_ok, tracker)
        assert should is False

    def test_consecutive_failure_strategy(self, tmp_db):
        """连续失败达到阈值触发告警."""
        task_config = TaskConfig(name="consec_alert", script_path="/tmp/t.py")
        record = TaskRecord(id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py")
        tmp_db.add_task(record)

        # Directly insert 3 failed execution records
        from datetime import datetime, timedelta
        now = datetime.now()
        for i in range(3):
            exec_rec = TaskExecution(
                task_id=task_config.task_id,
                status="failed",
                start_time=now - timedelta(minutes=3 - i),
                end_time=now - timedelta(minutes=3 - i, seconds=-5),
                duration=5.0,
                return_code=1,
                error=f"err {i}",
            )
            tmp_db.add_execution(exec_rec)

        tracker = ExecutionTracker(db_manager=tmp_db)
        strategy = ConsecutiveFailureStrategy(threshold=3)

        execution = TaskExecution(
            task_id=task_config.task_id,
            status="failed",
            return_code=1,
            error="error",
        )
        should, msg = strategy.should_alert(task_config.task_id, execution, tracker)
        assert should is True
        assert "Consecutive Failure" in msg


class TestAlertManager:
    """测试 AlertManager."""

    def _make_alert_manager(self, tmp_db, cooldown=300):
        config = AlertConfig(
            failure_immediate=True,
            consecutive_failure_threshold=3,
            cooldown_seconds=cooldown,
        )
        tracker = ExecutionTracker(db_manager=tmp_db)
        metrics = MetricsCollector(db_manager=tmp_db)
        return AlertManager(config=config, db_manager=tmp_db, tracker=tracker, metrics=metrics), tracker

    def test_alert_cooldown(self, tmp_db):
        """冷却期内不重复告警."""
        task_config = TaskConfig(name="cooldown_test", script_path="/tmp/t.py")
        record = TaskRecord(id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py")
        tmp_db.add_task(record)

        am, tracker = self._make_alert_manager(tmp_db, cooldown=3600)

        execution = TaskExecution(
            task_id=task_config.task_id,
            status="failed",
            return_code=1,
            error="fail",
        )

        # First alert should fire
        am.check_and_alert(task_config.task_id, execution)
        logs1 = tmp_db.list_alert_logs(task_id=task_config.task_id)
        count1 = len(logs1)
        assert count1 > 0

        # Second alert within cooldown should NOT add new log for the same type
        am.check_and_alert(task_config.task_id, execution)
        logs2 = tmp_db.list_alert_logs(task_id=task_config.task_id)
        count2 = len(logs2)
        # Should be same count (cooldown prevents re-alert)
        assert count2 == count1

    def test_alert_log_persistence(self, tmp_db):
        """告警日志正确保存到数据库."""
        task_config = TaskConfig(name="log_persist", script_path="/tmp/t.py")
        record = TaskRecord(id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py")
        tmp_db.add_task(record)

        am, tracker = self._make_alert_manager(tmp_db, cooldown=0)

        execution = TaskExecution(
            task_id=task_config.task_id,
            status="failed",
            return_code=1,
            error="test error",
        )
        am.check_and_alert(task_config.task_id, execution)

        logs = tmp_db.list_alert_logs(task_id=task_config.task_id)
        assert len(logs) > 0
        assert logs[0].task_id == task_config.task_id
        assert logs[0].success is True
