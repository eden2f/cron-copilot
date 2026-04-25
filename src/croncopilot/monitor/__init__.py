"""Monitor subsystem — execution tracking, metrics, and alerting."""

from croncopilot.monitor.alert import (
    AlertManager,
    AlertStrategy,
    ConsecutiveFailureStrategy,
    EmailNotifier,
    ImmediateFailureStrategy,
    PerformanceThresholdStrategy,
)
from croncopilot.monitor.metrics import MetricsCollector
from croncopilot.monitor.tracker import ExecutionTracker

__all__ = [
    "AlertManager",
    "AlertStrategy",
    "ConsecutiveFailureStrategy",
    "EmailNotifier",
    "ExecutionTracker",
    "ImmediateFailureStrategy",
    "MetricsCollector",
    "PerformanceThresholdStrategy",
]
