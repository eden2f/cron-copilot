"""CLI 入口 main.py 集成测试."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from click.testing import CliRunner

from croncopilot.main import cli


# ======================================================================
# Helpers
# ======================================================================


def _make_config():
    """构造一个最小化的 mock AppConfig."""
    config = MagicMock()
    config.storage.db_path = "/tmp/test.db"
    config.log.log_dir = "/tmp/logs"
    config.log.level = "INFO"
    config.log.max_days = 30
    config.log.json_format = False
    config.scheduler.max_workers = 2
    config.script = MagicMock()
    config.alert = MagicMock()
    config.recovery = MagicMock()
    config.recovery.cpu_threshold = 90.0
    config.recovery.memory_threshold = 90.0
    config.recovery.disk_threshold = 90.0
    config.pid_file = "/tmp/test.pid"
    return config


def _make_db_manager():
    """构造一个 mock DatabaseManager."""
    return MagicMock()


def _make_task_record(**overrides):
    """构造一个 mock 任务记录."""
    defaults = dict(
        id="task-001",
        name="demo_task",
        schedule_type="cron",
        cron_expression="*/5 * * * *",
        enabled=True,
        priority=5,
        category="test",
        holiday_mode="none",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ======================================================================
# P0 — init / start / stop
# ======================================================================


class TestInitCommand:
    """init 命令测试."""

    def test_init_creates_dirs_and_config(self, tmp_dir):
        """init 创建目录结构、配置文件、初始化数据库."""
        runner = CliRunner()
        base = os.path.join(tmp_dir, ".croncopilot")
        config_path = os.path.join(base, "config.yaml")

        with patch("croncopilot.main._BASE_DIR", base), \
             patch("croncopilot.main._DEFAULT_CONFIG_PATH", config_path), \
             patch("croncopilot.config.loader.ConfigLoader") as MockLoader, \
             patch("croncopilot.storage.database.DatabaseManager") as MockDB:
            mock_cfg = _make_config()
            MockLoader.return_value.load.return_value = mock_cfg

            result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0, result.output
        assert "创建目录" in result.output
        assert os.path.isdir(os.path.join(base, "logs"))
        assert os.path.isdir(os.path.join(base, "scripts"))
        assert os.path.isdir(os.path.join(base, "script_versions"))
        assert "初始化完成" in result.output

    def test_init_existing_config(self, tmp_dir):
        """init 对已有配置文件不覆盖."""
        runner = CliRunner()
        base = os.path.join(tmp_dir, ".croncopilot")
        os.makedirs(base, exist_ok=True)
        config_path = os.path.join(base, "config.yaml")
        with open(config_path, "w") as f:
            f.write("existing: true\n")

        with patch("croncopilot.main._BASE_DIR", base), \
             patch("croncopilot.main._DEFAULT_CONFIG_PATH", config_path), \
             patch("croncopilot.config.loader.ConfigLoader") as MockLoader, \
             patch("croncopilot.storage.database.DatabaseManager"):
            MockLoader.return_value.load.return_value = _make_config()
            result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0, result.output
        assert "配置文件已存在" in result.output

    def test_init_db_failure(self, tmp_dir):
        """init 在数据库初始化失败时输出错误."""
        runner = CliRunner()
        base = os.path.join(tmp_dir, ".croncopilot")
        config_path = os.path.join(base, "config.yaml")

        with patch("croncopilot.main._BASE_DIR", base), \
             patch("croncopilot.main._DEFAULT_CONFIG_PATH", config_path), \
             patch("croncopilot.config.loader.ConfigLoader") as MockLoader, \
             patch("croncopilot.storage.database.DatabaseManager", side_effect=RuntimeError("db error")):
            MockLoader.return_value.load.return_value = _make_config()
            result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0  # init 不会 sys.exit(1)
        assert "数据库初始化失败" in result.output


class TestStartCommand:
    """start 命令测试."""

    @patch("croncopilot.main._init_components")
    @patch("croncopilot.main.time")
    @patch("croncopilot.main.signal")
    def test_start_foreground(self, mock_signal, mock_time, mock_init):
        """start --foreground 正常启动."""
        call_count = 0

        def _sleep_side_effect(secs):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt

        mock_time.sleep.side_effect = _sleep_side_effect

        components = {
            "config": _make_config(),
            "loader": MagicMock(),
            "scheduler": MagicMock(),
            "health_checker": MagicMock(),
            "deadlock_detector": MagicMock(),
        }
        mock_init.return_value = components

        runner = CliRunner()
        with patch("croncopilot.deploy.daemon.DaemonManager") as MockDM:
            result = runner.invoke(cli, ["start"])

        assert "正在启动" in result.output
        components["scheduler"].start.assert_called_once()
        components["health_checker"].start.assert_called_once()
        components["deadlock_detector"].start.assert_called_once()

    @patch("croncopilot.main._init_components")
    def test_start_init_failure(self, mock_init):
        """start 初始化失败时 exit(1)."""
        mock_init.side_effect = RuntimeError("config not found")
        runner = CliRunner()
        result = runner.invoke(cli, ["start"])

        assert result.exit_code != 0
        assert "初始化失败" in result.output

    @patch("croncopilot.main._init_components")
    @patch("croncopilot.main.time")
    @patch("croncopilot.main.signal")
    def test_start_scheduler_failure(self, mock_signal, mock_time, mock_init):
        """start 调度器启动失败时 exit(1)."""
        components = {
            "config": _make_config(),
            "loader": MagicMock(),
            "scheduler": MagicMock(),
            "health_checker": MagicMock(),
            "deadlock_detector": MagicMock(),
        }
        components["scheduler"].start.side_effect = RuntimeError("scheduler boom")
        mock_init.return_value = components

        runner = CliRunner()
        with patch("croncopilot.deploy.daemon.DaemonManager"):
            result = runner.invoke(cli, ["start"])

        assert result.exit_code != 0
        assert "调度器启动失败" in result.output


class TestStopCommand:
    """stop 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_stop_running(self, mock_init_light):
        """stop 正常停止正在运行的进程."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.deploy.daemon.DaemonManager") as MockDM:
            dm = MockDM.return_value
            dm.is_running.return_value = True
            dm.get_pid.return_value = 12345
            dm.stop.return_value = True
            result = runner.invoke(cli, ["stop"])

        assert result.exit_code == 0
        assert "已停止" in result.output

    @patch("croncopilot.main._init_light")
    def test_stop_not_running(self, mock_init_light):
        """stop 在未运行时提示."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.deploy.daemon.DaemonManager") as MockDM:
            dm = MockDM.return_value
            dm.is_running.return_value = False
            result = runner.invoke(cli, ["stop"])

        assert result.exit_code == 0
        assert "未在运行" in result.output

    @patch("croncopilot.main._init_light")
    def test_stop_failure(self, mock_init_light):
        """stop 停止失败时 exit(1)."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.deploy.daemon.DaemonManager") as MockDM:
            dm = MockDM.return_value
            dm.is_running.return_value = True
            dm.get_pid.return_value = 12345
            dm.stop.return_value = False
            result = runner.invoke(cli, ["stop"])

        assert result.exit_code != 0
        assert "停止失败" in result.output

    def test_stop_config_load_failure(self):
        """stop 配置加载失败时使用默认路径."""
        runner = CliRunner()
        with patch("croncopilot.main._init_light", side_effect=RuntimeError("no config")), \
             patch("croncopilot.config.schema.default_config") as mock_default, \
             patch("croncopilot.deploy.daemon.DaemonManager") as MockDM:
            cfg = _make_config()
            cfg.pid_file = "/tmp/test.pid"
            mock_default.return_value = cfg
            dm = MockDM.return_value
            dm.is_running.return_value = False
            result = runner.invoke(cli, ["stop"])

        assert result.exit_code == 0
        assert "未在运行" in result.output


# ======================================================================
# P1 — task subcommands
# ======================================================================


class TestTaskAdd:
    """task add 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_task_add_success(self, mock_init_light):
        """task add 成功添加任务."""
        config = _make_config()
        db = _make_db_manager()
        db.get_task_by_name.return_value = None
        mock_init_light.return_value = (config, db)

        runner = CliRunner()
        with patch("croncopilot.main.os.path.isfile", return_value=True), \
             patch("croncopilot.core.task.parse_schedule"), \
             patch("croncopilot.core.task.TaskConfig") as MockTC, \
             patch("croncopilot.core.task.task_config_to_record") as mock_to_record:
            MockTC.return_value.task_id = "new-id-123"
            result = runner.invoke(cli, [
                "task", "add",
                "-n", "my_task",
                "-s", "/tmp/script.py",
                "-t", "cron",
                "-S", "*/5 * * * *",
            ])

        assert result.exit_code == 0, result.output
        assert "已添加" in result.output
        db.add_task.assert_called_once()

    @patch("croncopilot.main._init_light")
    def test_task_add_script_not_found(self, mock_init_light):
        """task add 脚本不存在时报错."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.main.os.path.isfile", return_value=False):
            result = runner.invoke(cli, [
                "task", "add",
                "-n", "my_task",
                "-s", "/nonexistent/script.py",
                "-t", "cron",
                "-S", "*/5 * * * *",
            ])

        assert result.exit_code != 0
        assert "脚本文件不存在" in result.output

    @patch("croncopilot.main._init_light")
    def test_task_add_invalid_schedule(self, mock_init_light):
        """task add 无效调度表达式报错."""
        db = _make_db_manager()
        mock_init_light.return_value = (_make_config(), db)

        runner = CliRunner()
        with patch("croncopilot.main.os.path.isfile", return_value=True), \
             patch("croncopilot.core.task.parse_schedule", side_effect=ValueError("bad expr")):
            result = runner.invoke(cli, [
                "task", "add",
                "-n", "bad_task",
                "-s", "/tmp/script.py",
                "-t", "cron",
                "-S", "invalid",
            ])

        assert result.exit_code != 0
        assert "调度表达式无效" in result.output

    @patch("croncopilot.main._init_light")
    def test_task_add_duplicate_name(self, mock_init_light):
        """task add 重名任务报错."""
        db = _make_db_manager()
        db.get_task_by_name.return_value = _make_task_record()
        mock_init_light.return_value = (_make_config(), db)

        runner = CliRunner()
        with patch("croncopilot.main.os.path.isfile", return_value=True), \
             patch("croncopilot.core.task.parse_schedule"):
            result = runner.invoke(cli, [
                "task", "add",
                "-n", "demo_task",
                "-s", "/tmp/script.py",
                "-t", "cron",
                "-S", "*/5 * * * *",
            ])

        assert result.exit_code != 0
        assert "已存在" in result.output

    def test_task_add_missing_required(self):
        """task add 缺少必需参数报错."""
        runner = CliRunner()
        result = runner.invoke(cli, ["task", "add", "-n", "only_name"])
        assert result.exit_code != 0


class TestTaskList:
    """task list 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_task_list_empty(self, mock_init_light):
        """task list 无任务时提示."""
        db = _make_db_manager()
        db.list_tasks.return_value = []
        mock_init_light.return_value = (_make_config(), db)

        runner = CliRunner()
        result = runner.invoke(cli, ["task", "list"])

        assert result.exit_code == 0
        assert "暂无任务" in result.output

    @patch("croncopilot.main._init_light")
    def test_task_list_with_tasks(self, mock_init_light):
        """task list 正常列出任务."""
        db = _make_db_manager()
        db.list_tasks.return_value = [
            _make_task_record(name="task_a"),
            _make_task_record(name="task_b", enabled=False),
        ]
        mock_init_light.return_value = (_make_config(), db)

        runner = CliRunner()
        result = runner.invoke(cli, ["task", "list"])

        assert result.exit_code == 0
        assert "task_a" in result.output
        assert "task_b" in result.output
        assert "共 2 个任务" in result.output


class TestTaskRun:
    """task run 命令测试."""

    @patch("croncopilot.main._init_light")
    @patch("croncopilot.main.setup_logging")
    @patch("croncopilot.main.time")
    def test_task_run_success(self, mock_time, mock_setup_log, mock_init_light):
        """task run 成功执行任务."""
        config = _make_config()
        db = _make_db_manager()
        db.get_task_by_name.return_value = _make_task_record()
        mock_init_light.return_value = (config, db)

        # Mock executor
        with patch("croncopilot.core.task.record_to_task_config") as mock_r2t, \
             patch("croncopilot.core.executor.TaskExecutor") as MockExec:
            mock_r2t.return_value = MagicMock(task_id="task-001")
            executor = MockExec.return_value
            executor.submit.return_value = True
            executor.get_running_tasks.return_value = []

            latest = MagicMock()
            latest.status = "success"
            latest.duration = 1.23
            db.get_latest_execution.return_value = latest

            runner = CliRunner()
            result = runner.invoke(cli, ["task", "run", "demo_task"])

        assert result.exit_code == 0, result.output
        assert "执行成功" in result.output

    @patch("croncopilot.main._init_light")
    def test_task_run_not_found(self, mock_init_light):
        """task run 任务不存在报错."""
        db = _make_db_manager()
        db.get_task_by_name.return_value = None
        mock_init_light.return_value = (_make_config(), db)

        runner = CliRunner()
        result = runner.invoke(cli, ["task", "run", "nonexist"])

        assert result.exit_code != 0
        assert "不存在" in result.output


class TestTaskRemove:
    """task remove 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_task_remove_force(self, mock_init_light):
        """task remove --force 直接删除."""
        db = _make_db_manager()
        db.get_task_by_name.return_value = _make_task_record()
        mock_init_light.return_value = (_make_config(), db)

        runner = CliRunner()
        result = runner.invoke(cli, ["task", "remove", "demo_task", "--force"])

        assert result.exit_code == 0, result.output
        assert "已删除" in result.output
        db.delete_task.assert_called_once()

    @patch("croncopilot.main._init_light")
    def test_task_remove_not_found(self, mock_init_light):
        """task remove 任务不存在报错."""
        db = _make_db_manager()
        db.get_task_by_name.return_value = None
        mock_init_light.return_value = (_make_config(), db)

        runner = CliRunner()
        result = runner.invoke(cli, ["task", "remove", "ghost_task", "--force"])

        assert result.exit_code != 0
        assert "不存在" in result.output


# ======================================================================
# P1 — status / health
# ======================================================================


class TestStatusCommand:
    """status 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_status_running(self, mock_init_light):
        """status 显示运行中状态与任务列表."""
        config = _make_config()
        db = _make_db_manager()
        db.list_tasks.return_value = [_make_task_record()]
        mock_init_light.return_value = (config, db)

        runner = CliRunner()
        with patch("croncopilot.deploy.daemon.DaemonManager") as MockDM:
            dm = MockDM.return_value
            dm.is_running.return_value = True
            dm.get_pid.return_value = 99999
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "运行中" in result.output
        assert "已注册任务" in result.output

    @patch("croncopilot.main._init_light")
    def test_status_not_running(self, mock_init_light):
        """status 显示未运行状态."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.deploy.daemon.DaemonManager") as MockDM:
            dm = MockDM.return_value
            dm.is_running.return_value = False
            dm.get_pid.return_value = None
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "未运行" in result.output

    @patch("croncopilot.main._init_light")
    def test_status_config_failure(self, mock_init_light):
        """status 配置加载失败时 exit(1)."""
        mock_init_light.side_effect = RuntimeError("bad config")

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])

        assert result.exit_code != 0
        assert "无法加载配置" in result.output


class TestHealthCommand:
    """health 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_health_all_ok(self, mock_init_light):
        """health 全部正常."""
        config = _make_config()
        db = _make_db_manager()
        mock_init_light.return_value = (config, db)

        runner = CliRunner()
        with patch("croncopilot.monitor.metrics.MetricsCollector") as MockMetrics:
            MockMetrics.return_value.get_system_metrics.return_value = {
                "cpu_percent": 30.0,
                "memory_percent": 50.0,
                "disk_percent": 60.0,
                "load_average": 1.5,
            }
            result = runner.invoke(cli, ["health"])

        assert result.exit_code == 0
        assert "系统健康" in result.output

    @patch("croncopilot.main._init_light")
    def test_health_warning(self, mock_init_light):
        """health 存在告警项."""
        config = _make_config()
        db = _make_db_manager()
        mock_init_light.return_value = (config, db)

        runner = CliRunner()
        with patch("croncopilot.monitor.metrics.MetricsCollector") as MockMetrics:
            MockMetrics.return_value.get_system_metrics.return_value = {
                "cpu_percent": 95.0,
                "memory_percent": 50.0,
                "disk_percent": 60.0,
                "load_average": 3.0,
            }
            result = runner.invoke(cli, ["health"])

        assert result.exit_code == 0
        assert "存在告警项" in result.output

    @patch("croncopilot.main._init_light")
    def test_health_init_failure(self, mock_init_light):
        """health 初始化失败时 exit(1)."""
        mock_init_light.side_effect = RuntimeError("no config")

        runner = CliRunner()
        result = runner.invoke(cli, ["health"])

        assert result.exit_code != 0
        assert "初始化失败" in result.output


# ======================================================================
# P1 — script subcommands
# ======================================================================


class TestScriptAdd:
    """script add 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_script_add_success(self, mock_init_light):
        """script add 成功注册."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.scripts.manager.ScriptManager") as MockSM:
            metadata = MagicMock()
            metadata.name = "my_script"
            metadata.path = "/tmp/my_script.py"
            MockSM.return_value.register.return_value = metadata
            result = runner.invoke(cli, [
                "script", "add", "-p", "/tmp/my_script.py",
            ])

        assert result.exit_code == 0, result.output
        assert "已注册" in result.output

    @patch("croncopilot.main._init_light")
    def test_script_add_file_not_found(self, mock_init_light):
        """script add 文件不存在报错."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.scripts.manager.ScriptManager") as MockSM:
            MockSM.return_value.register.side_effect = FileNotFoundError("not found")
            result = runner.invoke(cli, [
                "script", "add", "-p", "/nonexistent.py",
            ])

        assert result.exit_code != 0
        assert "not found" in result.output


class TestScriptList:
    """script list 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_script_list_empty(self, mock_init_light):
        """script list 无脚本时提示."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.scripts.manager.ScriptManager") as MockSM:
            MockSM.return_value.list_scripts.return_value = []
            result = runner.invoke(cli, ["script", "list"])

        assert result.exit_code == 0
        assert "暂无已注册脚本" in result.output

    @patch("croncopilot.main._init_light")
    def test_script_list_with_scripts(self, mock_init_light):
        """script list 正常列出脚本."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        s = SimpleNamespace(
            name="my_script", author="alice", category="util",
            version_count=2, path="/tmp/my_script.py",
        )
        runner = CliRunner()
        with patch("croncopilot.scripts.manager.ScriptManager") as MockSM:
            MockSM.return_value.list_scripts.return_value = [s]
            result = runner.invoke(cli, ["script", "list"])

        assert result.exit_code == 0
        assert "my_script" in result.output
        assert "共 1 个脚本" in result.output


class TestScriptInfo:
    """script info 命令测试."""

    @patch("croncopilot.main._init_light")
    def test_script_info_found(self, mock_init_light):
        """script info 显示脚本详情."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        info = SimpleNamespace(
            name="my_script", path="/tmp/my_script.py", author="alice",
            description="A test script", category="util", venv_path="",
            file_hash="abcdef1234567890", version_count=1,
            created_at="2025-01-01", updated_at="2025-01-02",
        )
        runner = CliRunner()
        with patch("croncopilot.scripts.manager.ScriptManager") as MockSM:
            MockSM.return_value.get_info.return_value = info
            MockSM.return_value.get_versions.return_value = []
            result = runner.invoke(cli, ["script", "info", "my_script"])

        assert result.exit_code == 0
        assert "my_script" in result.output
        assert "alice" in result.output

    @patch("croncopilot.main._init_light")
    def test_script_info_not_found(self, mock_init_light):
        """script info 脚本不存在报错."""
        mock_init_light.return_value = (_make_config(), _make_db_manager())

        runner = CliRunner()
        with patch("croncopilot.scripts.manager.ScriptManager") as MockSM:
            MockSM.return_value.get_info.return_value = None
            result = runner.invoke(cli, ["script", "info", "ghost"])

        assert result.exit_code != 0
        assert "不存在" in result.output


# ======================================================================
# CLI group options
# ======================================================================


class TestCliGroupOptions:
    """顶级命令组选项测试."""

    def test_verbose_flag(self):
        """--verbose 标志正确传递."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--verbose", "--help"])
        assert result.exit_code == 0

    def test_config_option(self):
        """--config 选项正确传递."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--config", "/tmp/custom.yaml", "--help"])
        assert result.exit_code == 0

    def test_help(self):
        """--help 输出帮助信息."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "CronCopilot" in result.output
