"""节假日识别功能测试"""
import datetime
import uuid

import pytest
from unittest.mock import patch, MagicMock, PropertyMock


# ---------------------------------------------------------------------------
# HolidayChecker 各模式测试
# ---------------------------------------------------------------------------


class TestHolidayChecker:
    """测试 HolidayChecker.should_execute 各 holiday_mode."""

    @pytest.fixture(autouse=True)
    def _patch_holiday_lib(self):
        """统一 mock chinesecalendar，避免依赖真实日历库."""
        mock_cc = MagicMock()
        with patch.dict("sys.modules", {"chinese_calendar": mock_cc}):
            # 重置全局缓存，确保每个测试独立
            import croncopilot.core.holiday as hmod
            hmod._holiday_lib = mock_cc
            self._mock_cc = mock_cc
            yield
            hmod._holiday_lib = None
            hmod._global_checker = None

    def _make_checker(self, enabled=True):
        from croncopilot.core.holiday import HolidayChecker
        return HolidayChecker(enabled=enabled)

    # --- mode = none ---

    def test_should_execute_mode_none(self):
        """holiday_mode='none' 始终返回 True"""
        checker = self._make_checker()
        date = datetime.date(2026, 1, 1)
        assert checker.should_execute(date, "none") is True

    # --- workday_only ---

    def test_should_execute_workday_only_on_workday(self):
        """workday_only 模式，工作日应执行"""
        self._mock_cc.is_workday.return_value = True
        checker = self._make_checker()
        date = datetime.date(2026, 4, 20)  # 假设工作日
        assert checker.should_execute(date, "workday_only") is True

    def test_should_execute_workday_only_on_holiday(self):
        """workday_only 模式，节假日不执行"""
        self._mock_cc.is_workday.return_value = False
        checker = self._make_checker()
        date = datetime.date(2026, 10, 1)
        assert checker.should_execute(date, "workday_only") is False

    # --- holiday_only ---

    def test_should_execute_holiday_only_on_holiday(self):
        """holiday_only 模式，节假日应执行"""
        self._mock_cc.is_workday.return_value = False
        checker = self._make_checker()
        date = datetime.date(2026, 10, 1)
        assert checker.should_execute(date, "holiday_only") is True

    def test_should_execute_holiday_only_on_workday(self):
        """holiday_only 模式，工作日不执行"""
        self._mock_cc.is_workday.return_value = True
        checker = self._make_checker()
        date = datetime.date(2026, 4, 20)
        assert checker.should_execute(date, "holiday_only") is False

    # --- skip_holiday ---

    def test_should_execute_skip_holiday_on_workday(self):
        """skip_holiday 模式，工作日应执行"""
        self._mock_cc.is_workday.return_value = True
        checker = self._make_checker()
        date = datetime.date(2026, 4, 20)
        assert checker.should_execute(date, "skip_holiday") is True

    def test_should_execute_skip_holiday_on_holiday(self):
        """skip_holiday 模式，节假日跳过"""
        self._mock_cc.is_workday.return_value = False
        checker = self._make_checker()
        date = datetime.date(2026, 10, 1)
        assert checker.should_execute(date, "skip_holiday") is False

    # --- skip_workday ---

    def test_should_execute_skip_workday_on_workday(self):
        """skip_workday 模式，工作日跳过"""
        self._mock_cc.is_workday.return_value = True
        checker = self._make_checker()
        date = datetime.date(2026, 4, 20)
        assert checker.should_execute(date, "skip_workday") is False

    def test_should_execute_skip_workday_on_holiday(self):
        """skip_workday 模式，节假日应执行"""
        self._mock_cc.is_workday.return_value = False
        checker = self._make_checker()
        date = datetime.date(2026, 10, 1)
        assert checker.should_execute(date, "skip_workday") is True

    # --- unknown mode ---

    def test_should_execute_unknown_mode(self):
        """未知 mode 默认执行"""
        checker = self._make_checker()
        date = datetime.date(2026, 5, 1)
        assert checker.should_execute(date, "some_unknown_mode") is True

    # --- disabled ---

    def test_disabled_checker_always_executes(self):
        """禁用状态下始终返回 True"""
        checker = self._make_checker(enabled=False)
        date = datetime.date(2026, 10, 1)
        # 即使是 workday_only，disabled 也应返回 True
        assert checker.should_execute(date, "workday_only") is True
        assert checker.should_execute(date, "holiday_only") is True
        assert checker.should_execute(date, "skip_holiday") is True


# ---------------------------------------------------------------------------
# HolidayChecker 基础方法测试
# ---------------------------------------------------------------------------


class TestHolidayCheckerBasic:
    """测试 is_workday / is_holiday 代理方法."""

    @pytest.fixture(autouse=True)
    def _patch_holiday_lib(self):
        mock_cc = MagicMock()
        with patch.dict("sys.modules", {"chinese_calendar": mock_cc}):
            import croncopilot.core.holiday as hmod
            hmod._holiday_lib = mock_cc
            self._mock_cc = mock_cc
            yield
            hmod._holiday_lib = None
            hmod._global_checker = None

    def test_is_workday(self):
        """测试 is_workday 代理到 chinese_calendar"""
        from croncopilot.core.holiday import HolidayChecker
        self._mock_cc.is_workday.return_value = True
        checker = HolidayChecker(enabled=True)
        date = datetime.date(2026, 4, 20)
        assert checker.is_workday(date) is True
        self._mock_cc.is_workday.assert_called_with(date)

    def test_is_holiday(self):
        """测试 is_holiday 代理到 chinese_calendar"""
        from croncopilot.core.holiday import HolidayChecker
        self._mock_cc.is_holiday.return_value = True
        checker = HolidayChecker(enabled=True)
        date = datetime.date(2026, 10, 1)
        assert checker.is_holiday(date) is True
        self._mock_cc.is_holiday.assert_called_with(date)

    def test_is_workday_disabled(self):
        """禁用时 is_workday 始终返回 True"""
        from croncopilot.core.holiday import HolidayChecker
        checker = HolidayChecker(enabled=False)
        assert checker.is_workday(datetime.date(2026, 10, 1)) is True

    def test_is_holiday_disabled(self):
        """禁用时 is_holiday 始终返回 False"""
        from croncopilot.core.holiday import HolidayChecker
        checker = HolidayChecker(enabled=False)
        assert checker.is_holiday(datetime.date(2026, 10, 1)) is False


# ---------------------------------------------------------------------------
# TaskConfig 序列化 holiday_mode 测试
# ---------------------------------------------------------------------------


class TestTaskConfigHolidayMode:
    """测试 TaskConfig 的 holiday_mode 字段序列化/反序列化."""

    def test_task_config_default_holiday_mode(self):
        """默认 holiday_mode 为 'none'"""
        from croncopilot.core.task import TaskConfig
        tc = TaskConfig(name="test", script_path="/tmp/t.py")
        assert tc.holiday_mode == "none"

    def test_task_config_to_record_with_holiday_mode(self):
        """TaskConfig -> TaskRecord 正确映射 holiday_mode"""
        from croncopilot.core.task import TaskConfig, task_config_to_record
        tc = TaskConfig(
            name="hm_test",
            script_path="/tmp/t.py",
            holiday_mode="workday_only",
        )
        record = task_config_to_record(tc)
        assert record.holiday_mode == "workday_only"

    def test_record_to_task_config_with_holiday_mode(self):
        """TaskRecord -> TaskConfig 正确还原 holiday_mode"""
        from croncopilot.core.task import TaskConfig, task_config_to_record, record_to_task_config
        tc = TaskConfig(
            name="hm_roundtrip",
            script_path="/tmp/t.py",
            holiday_mode="skip_holiday",
        )
        record = task_config_to_record(tc)
        restored = record_to_task_config(record)
        assert restored.holiday_mode == "skip_holiday"

    def test_record_to_task_config_none_holiday_mode(self):
        """TaskRecord.holiday_mode 为 None 时默认为 'none'"""
        from croncopilot.core.task import record_to_task_config
        from croncopilot.storage.models import TaskRecord
        record = TaskRecord(
            id=str(uuid.uuid4()),
            name="null_hm",
            script_path="/tmp/t.py",
            holiday_mode=None,
        )
        tc = record_to_task_config(record)
        assert tc.holiday_mode == "none"


# ---------------------------------------------------------------------------
# CLI --holiday-mode 参数测试
# ---------------------------------------------------------------------------


class TestCLIHolidayMode:
    """测试 CLI task add 的 --holiday-mode 选项."""

    def test_task_add_help_shows_holiday_mode(self):
        """task add --help 中包含 --holiday-mode 选项"""
        from click.testing import CliRunner
        from croncopilot.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["task", "add", "--help"])
        assert result.exit_code == 0
        assert "--holiday-mode" in result.output

    def test_task_add_with_holiday_mode(self, tmp_dir):
        """添加任务时指定 holiday_mode 被正确保存"""
        import os
        from click.testing import CliRunner
        from croncopilot.main import cli

        # 准备脚本文件
        script_path = os.path.join(tmp_dir, "task_hm.py")
        with open(script_path, "w") as f:
            f.write('print("hello")\n')

        # 准备配置和数据库
        config_path = os.path.join(tmp_dir, "config.yaml")
        db_path = os.path.join(tmp_dir, "test.db")
        import yaml
        cfg = {
            "scheduler": {"timezone": "Asia/Shanghai", "max_workers": 2},
            "storage": {"db_path": db_path},
            "log": {"log_dir": os.path.join(tmp_dir, "logs"), "level": "DEBUG", "max_days": 7, "json_format": False},
            "alert": {"email": {"enabled": False, "smtp_host": "", "smtp_port": 25, "sender": "", "recipients": []}},
            "recovery": {
                "max_retries": 3, "retry_delay": 60,
                "cpu_threshold": 90.0, "memory_threshold": 90.0, "disk_threshold": 90.0,
                "health_check_interval": 300,
            },
            "script": {"script_dir": os.path.join(tmp_dir, "scripts"), "version_dir": os.path.join(tmp_dir, "versions")},
            "pid_file": os.path.join(tmp_dir, "pcg.pid"),
        }
        with open(config_path, "w") as f:
            yaml.dump(cfg, f)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--config", config_path,
            "task", "add",
            "--name", "holiday_task",
            "--script", script_path,
            "--schedule-type", "daily",
            "--schedule", "08:00",
            "--holiday-mode", "workday_only",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "已添加" in result.output

        # 验证数据库中的 holiday_mode
        from croncopilot.storage.database import DatabaseManager
        db = DatabaseManager(db_path)
        record = db.get_task_by_name("holiday_task")
        assert record is not None
        assert record.holiday_mode == "workday_only"
