"""Monitor subsystem — execution tracking, metrics, and alerting."""

from pycronguard.monitor.alert import (
    AlertManager,
    AlertStrategy,
    ConsecutiveFailureStrategy,
    EmailNotifier,
    ImmediateFailureStrategy,
    PerformanceThresholdStrategy,
)
from pycronguard.monitor.metrics import MetricsCollector
from pycronguard.monitor.tracker import ExecutionTracker

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
