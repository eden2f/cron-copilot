"""SQLAlchemy ORM models for CronCopilot.

Uses the SQLAlchemy 2.0+ ``DeclarativeBase`` / ``Mapped`` style.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class TaskRecord(Base):
    """Registered cron task definition."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    script_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True)
    schedule_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="cron / daily / weekly / monthly"
    )
    priority: Mapped[int] = mapped_column(Integer, default=5)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    timeout: Mapped[int] = mapped_column(Integer, default=3600, comment="Seconds")
    dependencies: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="JSON-serialised list of dependent task IDs"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    venv_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="Optional virtualenv path"
    )
    max_instances: Mapped[int] = mapped_column(
        Integer, default=1, comment="Max concurrent instances for this task"
    )
    holiday_mode: Mapped[str | None] = mapped_column(
        String(32), default="none", nullable=True,
        comment="none / workday_only / holiday_only / skip_holiday / skip_workday",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<TaskRecord(id={self.id!r}, name={self.name!r})>"


class TaskExecution(Base):
    """Single execution record of a task."""

    __tablename__ = "task_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", comment="pending / running / success / failed"
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Seconds")
    return_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cpu_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<TaskExecution(id={self.id!r}, task_id={self.task_id!r}, status={self.status!r})>"


class ScriptMeta(Base):
    """Metadata for a managed script file."""

    __tablename__ = "script_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    venv_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ScriptMeta(id={self.id!r}, name={self.name!r})>"


class AlertLog(Base):
    """Alert delivery log entry."""

    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    alert_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="failure / consecutive_failure / performance"
    )
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="email"
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    success: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<AlertLog(id={self.id!r}, task_id={self.task_id!r}, alert_type={self.alert_type!r})>"
