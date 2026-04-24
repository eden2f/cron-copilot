"""Configuration schema definitions using dataclasses.

This module defines the complete configuration structure for PyCronGuard,
including nested dataclasses for each subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SchedulerConfig:
    """Scheduler-related configuration."""

    max_workers: int = 4
    max_instances: int = 1
    timezone: str = "Asia/Shanghai"


@dataclass
class StorageConfig:
    """Storage / database configuration."""

    db_path: str = "~/.pycronguard/data.db"


@dataclass
class LogConfig:
    """Logging configuration."""

    log_dir: str = "~/.pycronguard/logs"
    level: str = "INFO"
    max_days: int = 30
    json_format: bool = True


@dataclass
class AlertEmailConfig:
    """Email alert channel configuration."""

    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)


@dataclass
class AlertConfig:
    """Alert system configuration."""

    email: AlertEmailConfig = field(default_factory=AlertEmailConfig)
    failure_immediate: bool = True
    consecutive_failure_threshold: int = 3
    cooldown_seconds: int = 300


@dataclass
class RecoveryConfig:
    """Recovery and health-check configuration."""

    max_retries: int = 3
    retry_delay: float = 10.0
    backoff_factor: float = 2.0
    health_check_interval: int = 60
    cpu_threshold: float = 90.0
    memory_threshold: float = 90.0
    disk_threshold: float = 90.0
    task_timeout: int = 3600


@dataclass
class ScriptConfig:
    """Script management configuration."""

    script_dir: str = "~/.pycronguard/scripts"
    version_dir: str = "~/.pycronguard/script_versions"
    max_versions: int = 10


@dataclass
class AppConfig:
    """Top-level application configuration."""

    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    log: LogConfig = field(default_factory=LogConfig)
    alert: AlertConfig = field(default_factory=AlertConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    script: ScriptConfig = field(default_factory=ScriptConfig)
    pid_file: str = "~/.pycronguard/pycronguard.pid"


def default_config() -> AppConfig:
    """Return an ``AppConfig`` instance populated with sensible defaults.

    Returns:
        AppConfig: A fully-initialised default configuration object.
    """
    return AppConfig()


def validate_config(config: AppConfig) -> None:
    """Perform basic validation on an ``AppConfig`` instance.

    Raises:
        ValueError: If any configuration value is out of range or invalid.
    """
    if config.scheduler.max_workers < 1:
        raise ValueError("scheduler.max_workers must be >= 1")
    if config.scheduler.max_instances < 1:
        raise ValueError("scheduler.max_instances must be >= 1")

    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if config.log.level.upper() not in valid_levels:
        raise ValueError(f"log.level must be one of {valid_levels}")
    if config.log.max_days < 1:
        raise ValueError("log.max_days must be >= 1")

    if config.recovery.max_retries < 0:
        raise ValueError("recovery.max_retries must be >= 0")
    if config.recovery.retry_delay < 0:
        raise ValueError("recovery.retry_delay must be >= 0")
    if config.recovery.backoff_factor < 1.0:
        raise ValueError("recovery.backoff_factor must be >= 1.0")
    if config.recovery.task_timeout < 1:
        raise ValueError("recovery.task_timeout must be >= 1")

    for attr in ("cpu_threshold", "memory_threshold", "disk_threshold"):
        value = getattr(config.recovery, attr)
        if not 0.0 <= value <= 100.0:
            raise ValueError(f"recovery.{attr} must be between 0 and 100")

    if config.alert.consecutive_failure_threshold < 1:
        raise ValueError("alert.consecutive_failure_threshold must be >= 1")
    if config.alert.cooldown_seconds < 0:
        raise ValueError("alert.cooldown_seconds must be >= 0")

    if config.script.max_versions < 1:
        raise ValueError("script.max_versions must be >= 1")

    if config.alert.email.enabled:
        if not config.alert.email.smtp_host:
            raise ValueError("alert.email.smtp_host is required when email alerts are enabled")
        if not config.alert.email.recipients:
            raise ValueError("alert.email.recipients must not be empty when email alerts are enabled")
