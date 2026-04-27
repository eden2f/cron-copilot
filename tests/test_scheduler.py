"""调度器测试 — task 解析、转换和 SchedulerManager."""

import uuid
import pytest
from unittest.mock import MagicMock, patch

from croncopilot.core.task import (
    TaskConfig,
    parse_schedule,
    task_config_to_record,
    record_to_task_config,
)
from croncopilot.storage.models import TaskRecord


class TestParseSchedule:
    """测试调度表达式解析."""

    def test_parse_schedule_cron(self):
        """cron 表达式正确解析."""
        result = parse_schedule("cron", "0 8 * * *")
        assert result == {
            "minute": "0",
            "hour": "8",
            "day": "*",
            "month": "*",
            "day_of_week": "*",
        }

    def test_parse_schedule_daily(self):
        """daily 格式正确解析."""
        result = parse_schedule("daily", "08:00")
        assert result == {"hour": 8, "minute": 0}

    def test_parse_schedule_weekly(self):
        """weekly 格式正确解析."""
        result = parse_schedule("weekly", "mon@08:00")
        assert result == {"day_of_week": "mon", "hour": 8, "minute": 0}

    def test_parse_schedule_monthly(self):
        """monthly 格式正确解析."""
        result = parse_schedule("monthly", "1@08:00")
        assert result == {"day": 1, "hour": 8, "minute": 0}

    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("30m", {"minutes": 30}),
            ("2h", {"hours": 2}),
            ("1d", {"days": 1}),
            ("90s", {"seconds": 90}),
        ],
    )
    def test_parse_schedule_interval(self, expr, expected):
        """interval 格式（30m, 2h, 1d）正确解析."""
        result = parse_schedule("interval", expr)
        assert result == expected

    @pytest.mark.parametrize(
        "schedule_type,schedule_expr",
        [
            ("unknown", "something"),
            ("cron", "0 8 * *"),  # 4 fields instead of 5
            ("daily", "25:00"),
            ("weekly", "xyz@08:00"),
            ("monthly", "32@08:00"),
            ("interval", "abc"),
        ],
    )
    def test_parse_schedule_invalid(self, schedule_type, schedule_expr):
        """无效格式抛出 ValueError."""
        with pytest.raises(ValueError):
            parse_schedule(schedule_type, schedule_expr)


class TestTaskConversion:
    """测试 TaskConfig 与 TaskRecord 之间的转换."""

    def test_task_config_to_record(self, sample_task_config):
        """TaskConfig 正确转换为 TaskRecord."""
        record = task_config_to_record(sample_task_config)
        assert isinstance(record, TaskRecord)
        assert record.id == sample_task_config.task_id
        assert record.name == sample_task_config.name
        assert record.script_path == sample_task_config.script_path
        assert record.schedule_type == sample_task_config.schedule_type
        assert record.cron_expression == sample_task_config.schedule_expr
        assert record.priority == sample_task_config.priority
        assert record.max_retries == sample_task_config.max_retries
        assert record.timeout == sample_task_config.timeout

    def test_task_config_to_record_with_dependencies(self):
        """带依赖的 TaskConfig 转换时 dependencies 被 JSON 序列化."""
        config = TaskConfig(
            name="dep_task",
            script_path="/tmp/t.py",
            dependencies=["id1", "id2"],
        )
        record = task_config_to_record(config)
        import json
        assert json.loads(record.dependencies) == ["id1", "id2"]

    def test_record_to_task_config(self, sample_task_config):
        """TaskRecord 正确还原为 TaskConfig."""
        record = task_config_to_record(sample_task_config)
        restored = record_to_task_config(record)
        assert restored.task_id == sample_task_config.task_id
        assert restored.name == sample_task_config.name
        assert restored.script_path == sample_task_config.script_path
        assert restored.schedule_type == sample_task_config.schedule_type
        assert restored.schedule_expr == sample_task_config.schedule_expr
        assert restored.priority == sample_task_config.priority
        assert restored.max_retries == sample_task_config.max_retries
        assert restored.timeout == sample_task_config.timeout


class TestSchedulerManager:
    """测试 SchedulerManager."""

    def _make_scheduler(self, tmp_db, default_config):
        from croncopilot.core.executor import TaskExecutor
        from croncopilot.core.scheduler import SchedulerManager
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        sm = SchedulerManager(config=default_config, db_manager=tmp_db, executor=executor)
        return sm, executor

    def test_scheduler_add_task(self, tmp_db, default_config):
        """添加任务到调度器."""
        sm, executor = self._make_scheduler(tmp_db, default_config)
        config = TaskConfig(
            name="sched_test",
            script_path="/tmp/t.py",
            schedule_type="daily",
            schedule_expr="09:00",
        )
        task_id = sm.add_task(config)
        assert task_id == config.task_id
        assert sm.get_task(task_id) is not None
        executor.shutdown(wait=False)

    def test_scheduler_misfire_grace_time(self, tmp_db, default_config):
        """调度器 misfire_grace_time 应为 60 秒，避免错过的任务无限期补偿执行."""
        sm, executor = self._make_scheduler(tmp_db, default_config)
        job_defaults = sm._scheduler._job_defaults
        assert job_defaults.get('misfire_grace_time') == 60
        assert job_defaults.get('coalesce') is True
        assert job_defaults.get('max_instances') == 1
        executor.shutdown(wait=False)

    def test_scheduler_remove_task(self, tmp_db, default_config):
        """移除任务."""
        sm, executor = self._make_scheduler(tmp_db, default_config)
        config = TaskConfig(
            name="remove_test",
            script_path="/tmp/t.py",
            schedule_type="daily",
            schedule_expr="09:00",
        )
        task_id = sm.add_task(config)
        sm.remove_task(task_id)
        assert sm.get_task(task_id) is None
        executor.shutdown(wait=False)

    def test_scheduler_pause_resume(self, tmp_db, default_config):
        """暂停和恢复任务."""
        sm, executor = self._make_scheduler(tmp_db, default_config)
        sm.start()
        try:
            config = TaskConfig(
                name="pause_test",
                script_path="/tmp/t.py",
                schedule_type="interval",
                schedule_expr="30m",
            )
            task_id = sm.add_task(config)
            # Should not raise
            sm.pause_task(task_id)
            sm.resume_task(task_id)
        finally:
            sm.stop(wait=False)

    def test_scheduler_list_tasks(self, tmp_db, default_config):
        """列出所有任务."""
        sm, executor = self._make_scheduler(tmp_db, default_config)
        for i in range(3):
            config = TaskConfig(
                name=f"list_test_{i}",
                script_path="/tmp/t.py",
                schedule_type="daily",
                schedule_expr="09:00",
            )
            sm.add_task(config)
        tasks = sm.list_tasks()
        assert len(tasks) == 3
        executor.shutdown(wait=False)

    def test_run_task_now_trigger_type(self, tmp_db, default_config):
        """run_task_now() 调用 executor.submit() 时传递 trigger_type='manual' 和 skip_holiday_check=True."""
        sm, executor = self._make_scheduler(tmp_db, default_config)

        task_config = TaskConfig(
            name="run_now_trigger",
            script_path="/tmp/t.py",
            schedule_type="daily",
            schedule_expr="09:00",
        )
        sm.add_task(task_config)

        # Mock executor.submit to capture call args
        executor.submit = MagicMock(return_value=True)

        sm.run_task_now(task_config.task_id)

        executor.submit.assert_called_once()
        call_args = executor.submit.call_args
        assert call_args[0][0] is task_config
        assert call_args[1]["skip_holiday_check"] is True
        assert call_args[1]["trigger_type"] == "manual"

        executor.shutdown(wait=False)

    def test_task_wrapper_skips_when_retrying(self, tmp_db, default_config):
        """_task_wrapper 在任务正在重试时跳过 scheduled 触发."""
        from croncopilot.core.executor import TaskExecutor
        from croncopilot.core.scheduler import SchedulerManager

        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        sm = SchedulerManager(config=default_config, db_manager=tmp_db, executor=executor)

        task_config = TaskConfig(
            name="skip_when_retrying",
            script_path="/tmp/t.py",
            schedule_type="daily",
            schedule_expr="09:00",
        )
        sm.add_task(task_config)

        # Mock executor.submit to track if it gets called
        executor.submit = MagicMock(return_value=True)

        # Create a mock retry_manager that reports the task is retrying
        mock_retry_manager = MagicMock()
        mock_retry_manager.is_retrying.return_value = True
        sm.set_retry_manager(mock_retry_manager)

        # Call _task_wrapper directly — it should skip execution
        sm._task_wrapper(task_config.task_id)

        executor.submit.assert_not_called()
        mock_retry_manager.is_retrying.assert_called_once_with(task_config.task_id)

        executor.shutdown(wait=False)

    def test_task_wrapper_runs_when_not_retrying(self, tmp_db, default_config):
        """_task_wrapper 在任务未重试时正常执行."""
        from croncopilot.core.executor import TaskExecutor
        from croncopilot.core.scheduler import SchedulerManager

        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        sm = SchedulerManager(config=default_config, db_manager=tmp_db, executor=executor)

        task_config = TaskConfig(
            name="run_when_not_retrying",
            script_path="/tmp/t.py",
            schedule_type="daily",
            schedule_expr="09:00",
        )
        sm.add_task(task_config)

        # Mock executor.submit
        executor.submit = MagicMock(return_value=True)

        # Create a mock retry_manager that reports the task is NOT retrying
        mock_retry_manager = MagicMock()
        mock_retry_manager.is_retrying.return_value = False
        sm.set_retry_manager(mock_retry_manager)

        # Call _task_wrapper — it should proceed to submit
        sm._task_wrapper(task_config.task_id)

        executor.submit.assert_called_once()

        executor.shutdown(wait=False)
