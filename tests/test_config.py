"""配置模块测试 — schema 和 loader."""

import os
import pytest
import yaml

from pycronguard.config.schema import (
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
from pycronguard.config.loader import ConfigLoader


class TestDefaultConfig:
    """测试默认配置."""

    def test_default_config(self, default_config):
        """默认配置所有字段有正确的默认值."""
        assert isinstance(default_config, AppConfig)
        assert default_config.scheduler.max_workers == 4
        assert default_config.scheduler.max_instances == 1
        assert default_config.scheduler.timezone == "Asia/Shanghai"
        assert default_config.storage.db_path == "~/.pycronguard/data.db"
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
        assert default_config.pid_file == "~/.pycronguard/pycronguard.pid"


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
