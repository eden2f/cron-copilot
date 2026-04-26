"""配置模块测试 — schema 和 loader."""

import os
import pytest
import yaml

from croncopilot.config.schema import (
    AppConfig,
    SchedulerConfig,
    LogConfig,
    RecoveryConfig,
    AlertConfig,
    ScriptConfig,
    StorageConfig,
    default_config,
    validate_config,
)
from croncopilot.config.loader import ConfigLoader
from croncopilot.storage.models import TaskExecution, TaskRecord


class TestDefaultConfig:
    """测试默认配置."""

    def test_default_config(self, default_config):
        """默认配置所有字段有正确的默认值."""
        assert isinstance(default_config, AppConfig)
        assert default_config.scheduler.max_workers == 4
        assert default_config.scheduler.max_instances == 1
        assert default_config.scheduler.timezone == "Asia/Shanghai"
        assert default_config.storage.db_path == "~/.croncopilot/data.db"
        assert default_config.log.level == "INFO"
        assert default_config.log.max_days == 30
        assert default_config.log.json_format is True
        assert default_config.recovery.max_retries == 3
        assert default_config.recovery.retry_delay == 10.0
        assert default_config.recovery.backoff_factor == 2.0
        assert default_config.recovery.task_timeout == 3600
        assert default_config.alert.failure_immediate is True
        assert default_config.alert.consecutive_failure_threshold == 3
        assert default_config.alert.cooldown_seconds == 300
        assert default_config.alert.email.enabled is False
        assert default_config.script.max_versions == 10
        assert default_config.pid_file == "~/.croncopilot/croncopilot.pid"


class TestValidateConfig:
    """测试配置校验."""

    def test_validate_config_valid(self, default_config):
        """有效配置通过校验."""
        # Should not raise
        validate_config(default_config)

    @pytest.mark.parametrize(
        "field_path,value,error_msg",
        [
            ("scheduler.max_workers", 0, "scheduler.max_workers must be >= 1"),
            ("scheduler.max_workers", -1, "scheduler.max_workers must be >= 1"),
            ("scheduler.max_instances", 0, "scheduler.max_instances must be >= 1"),
            ("log.level", "INVALID", "log.level must be one of"),
            ("log.max_days", 0, "log.max_days must be >= 1"),
            ("recovery.max_retries", -1, "recovery.max_retries must be >= 0"),
            ("recovery.retry_delay", -1, "recovery.retry_delay must be >= 0"),
            ("recovery.backoff_factor", 0.5, "recovery.backoff_factor must be >= 1.0"),
            ("recovery.task_timeout", 0, "recovery.task_timeout must be >= 1"),
            ("recovery.cpu_threshold", 101, "recovery.cpu_threshold must be between 0 and 100"),
            ("recovery.memory_threshold", -1, "recovery.memory_threshold must be between 0 and 100"),
            ("alert.consecutive_failure_threshold", 0, "alert.consecutive_failure_threshold must be >= 1"),
            ("alert.cooldown_seconds", -1, "alert.cooldown_seconds must be >= 0"),
            ("script.max_versions", 0, "script.max_versions must be >= 1"),
        ],
    )
    def test_validate_config_invalid(self, field_path, value, error_msg):
        """无效配置（如 max_workers<=0）抛出异常."""
        config = default_config()
        parts = field_path.split(".")
        obj = config
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)

        with pytest.raises(ValueError, match=error_msg):
            validate_config(config)


class TestConfigLoader:
    """测试配置加载器."""

    def test_config_loader_default(self):
        """无配置文件时使用默认值."""
        loader = ConfigLoader(config_path=None)
        config = loader.load()
        assert isinstance(config, AppConfig)
        assert config.scheduler.max_workers == 4

    def test_config_loader_yaml(self, tmp_dir):
        """从 YAML 文件加载并合并配置."""
        yaml_content = {
            "scheduler": {"max_workers": 8, "timezone": "UTC"},
            "log": {"level": "DEBUG"},
        }
        yaml_path = os.path.join(tmp_dir, "config.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        loader = ConfigLoader(yaml_path)
        config = loader.load()
        assert config.scheduler.max_workers == 8
        assert config.scheduler.timezone == "UTC"
        assert config.log.level == "DEBUG"
        # 未覆盖的字段保持默认值
        assert config.recovery.max_retries == 3

    def test_config_loader_partial_yaml(self, tmp_dir):
        """部分配置的 YAML 与默认值正确合并."""
        yaml_content = {
            "scheduler": {"max_workers": 2},
        }
        yaml_path = os.path.join(tmp_dir, "partial.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        loader = ConfigLoader(yaml_path)
        config = loader.load()
        assert config.scheduler.max_workers == 2
        # max_instances should remain default
        assert config.scheduler.max_instances == 1
        assert config.scheduler.timezone == "Asia/Shanghai"

    def test_config_loader_path_expansion(self):
        """~ 路径正确展开."""
        loader = ConfigLoader(config_path=None)
        config = loader.load()
        home = os.path.expanduser("~")
        assert config.storage.db_path.startswith(home)
        assert config.log.log_dir.startswith(home)
        assert config.script.script_dir.startswith(home)
        assert config.pid_file.startswith(home)
        assert "~" not in config.storage.db_path


class TestDatabaseTriggerType:
    """测试数据库层 trigger_type 功能."""

    def test_list_executions_by_trigger(self, tmp_db):
        """list_executions_by_trigger() 正确按触发类型过滤."""
        from croncopilot.core.task import TaskConfig
        from datetime import datetime, timedelta

        task_config = TaskConfig(name="trigger_filter", script_path="/tmp/t.py")
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py"
        )
        tmp_db.add_task(record)

        now = datetime.now()
        # Add executions with different trigger_types
        for i, tt in enumerate(["scheduled", "manual", "retry", "scheduled", "manual"]):
            exec_rec = TaskExecution(
                task_id=task_config.task_id,
                status="success",
                start_time=now - timedelta(minutes=5 - i),
                trigger_type=tt,
            )
            tmp_db.add_execution(exec_rec)

        scheduled = tmp_db.list_executions_by_trigger(task_config.task_id, "scheduled")
        assert len(scheduled) == 2
        for e in scheduled:
            assert e.trigger_type == "scheduled"

        manual = tmp_db.list_executions_by_trigger(task_config.task_id, "manual")
        assert len(manual) == 2
        for e in manual:
            assert e.trigger_type == "manual"

        retry = tmp_db.list_executions_by_trigger(task_config.task_id, "retry")
        assert len(retry) == 1
        assert retry[0].trigger_type == "retry"

        health = tmp_db.list_executions_by_trigger(task_config.task_id, "health_check")
        assert len(health) == 0

    def test_old_records_trigger_type_none_compatibility(self, tmp_db):
        """旧记录（trigger_type 为 None）的兼容性."""
        from croncopilot.core.task import TaskConfig
        from datetime import datetime
        import sqlalchemy

        task_config = TaskConfig(name="old_record_compat", script_path="/tmp/t.py")
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name, script_path="/tmp/t.py"
        )
        tmp_db.add_task(record)

        # Insert a record with trigger_type=NULL via raw SQL
        # to simulate pre-migration data that truly has no trigger_type
        with tmp_db._engine.connect() as conn:
            conn.execute(sqlalchemy.text(
                "INSERT INTO task_executions (task_id, status, start_time, trigger_type, retry_count) "
                "VALUES (:tid, 'success', :st, NULL, 0)"
            ), {"tid": task_config.task_id, "st": datetime.now().isoformat()})
            conn.commit()

        # Verify the record can be read back with trigger_type=None
        execs = tmp_db.list_executions(task_config.task_id)
        assert len(execs) == 1
        assert execs[0].trigger_type is None

        # New records should have default trigger_type
        new_exec = TaskExecution(
            task_id=task_config.task_id,
            status="success",
            start_time=datetime.now(),
        )
        tmp_db.add_execution(new_exec)

        execs = tmp_db.list_executions(task_config.task_id)
        assert len(execs) == 2
        # The new record should have default 'scheduled'
        trigger_types = [e.trigger_type for e in execs]
        assert "scheduled" in trigger_types
        assert None in trigger_types
