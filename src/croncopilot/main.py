"""CronCopilot CLI entry point.

Provides the ``cli`` Click group and all sub-commands for managing the
CronCopilot task scheduling system.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import click

from croncopilot.logging.logger import get_logger, setup_logging

logger = get_logger(__name__)

# Default base directory
_BASE_DIR = os.path.expanduser("~/.croncopilot")
_DEFAULT_CONFIG_PATH = os.path.join(_BASE_DIR, "config.yaml")


# ======================================================================
# Component initialisation helpers
# ======================================================================


def _init_light(config_path: Optional[str] = None) -> Tuple[Any, Any]:
    """Lightweight initialisation: config + database only.

    Suitable for CLI management commands (task/script add/remove/list).

    Parameters:
        config_path: Optional path to a YAML configuration file.

    Returns:
        A ``(config, db_manager)`` tuple.
    """
    from croncopilot.config.loader import ConfigLoader
    from croncopilot.storage.database import DatabaseManager

    loader = ConfigLoader(config_path)
    config = loader.load()
    db_manager = DatabaseManager(config.storage.db_path)
    return config, db_manager


def _init_components(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Full initialisation for the scheduler runtime.

    Creates and wires together every subsystem component.

    Parameters:
        config_path: Optional path to a YAML configuration file.

    Returns:
        A dict containing all initialised components keyed by name.
    """
    from croncopilot.config.loader import ConfigLoader
    from croncopilot.config.schema import AppConfig
    from croncopilot.core.executor import TaskExecutor
    from croncopilot.core.scheduler import SchedulerManager
    from croncopilot.monitor.alert import AlertManager
    from croncopilot.monitor.metrics import MetricsCollector
    from croncopilot.monitor.tracker import ExecutionTracker
    from croncopilot.recovery.deadlock import DeadlockDetector
    from croncopilot.recovery.health import HealthChecker
    from croncopilot.recovery.retry import RetryManager
    from croncopilot.scripts.manager import ScriptManager
    from croncopilot.storage.database import DatabaseManager

    # 1. Load configuration
    loader = ConfigLoader(config_path)
    config: AppConfig = loader.load()

    # 2. Initialise logging
    setup_logging(
        log_dir=config.log.log_dir,
        level=config.log.level,
        max_days=config.log.max_days,
        json_format=config.log.json_format,
    )

    # 3. Initialise database
    db_manager = DatabaseManager(config.storage.db_path)

    # 4. Create executor
    executor = TaskExecutor(
        max_workers=config.scheduler.max_workers,
        db_manager=db_manager,
        record_to_db=False,
    )

    # 5. Create scheduler manager
    scheduler = SchedulerManager(config, db_manager, executor)

    # 6. Create script manager
    script_manager = ScriptManager(config.script, db_manager)

    # 7. Create monitoring components
    tracker = ExecutionTracker(db_manager)
    metrics = MetricsCollector(db_manager)
    alert_manager = AlertManager(config.alert, db_manager, tracker, metrics)

    # 8. Create recovery components
    retry_manager = RetryManager(config.recovery, executor, db_manager, tracker)
    health_checker = HealthChecker(
        config.recovery,
        metrics,
        scheduler_pause_callback=lambda: scheduler._scheduler.pause(),
        scheduler_resume_callback=lambda: scheduler._scheduler.resume(),
    )
    deadlock_detector = DeadlockDetector(
        config.recovery,
        executor,
        tracker,
    )

    # 9. Bind callback chains
    # tracker -> executor
    tracker.bind_executor(executor)
    # alert -> tracker
    alert_manager.bind_tracker(tracker)
    # retry -> executor
    retry_manager.bind_executor(executor)

    return {
        "config": config,
        "loader": loader,
        "db_manager": db_manager,
        "executor": executor,
        "scheduler": scheduler,
        "script_manager": script_manager,
        "tracker": tracker,
        "metrics": metrics,
        "alert_manager": alert_manager,
        "retry_manager": retry_manager,
        "health_checker": health_checker,
        "deadlock_detector": deadlock_detector,
    }


# ======================================================================
# CLI definition
# ======================================================================


@click.group()
@click.option("--config", "-c", default=None, help="配置文件路径")
@click.option("--verbose", "-v", is_flag=True, help="详细输出")
@click.pass_context
def cli(ctx: click.Context, config: Optional[str], verbose: bool) -> None:
    """CronCopilot - Python 定时任务管理系统"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose


# ------------------------------------------------------------------
# init
# ------------------------------------------------------------------


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """初始化 CronCopilot 配置和目录结构"""
    base_dir = _BASE_DIR

    # Create base directory
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    click.echo(f"✓ 创建目录: {base_dir}")

    # Create sub-directories
    for sub in ("logs", "scripts", "script_versions"):
        sub_dir = os.path.join(base_dir, sub)
        Path(sub_dir).mkdir(parents=True, exist_ok=True)
        click.echo(f"✓ 创建目录: {sub_dir}")

    # Create default config if not exists
    config_dest = _DEFAULT_CONFIG_PATH
    if not os.path.isfile(config_dest):
        # Try to copy bundled default config
        bundled = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config",
            "default_config.yaml",
        )
        # Fallback: look relative to project root
        if not os.path.isfile(bundled):
            bundled = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "config",
                "default_config.yaml",
            )

        if os.path.isfile(bundled):
            shutil.copy2(bundled, config_dest)
            click.echo(f"✓ 创建默认配置: {config_dest}")
        else:
            # Generate a minimal config
            from croncopilot.config.schema import default_config
            from dataclasses import asdict
            import yaml

            cfg = asdict(default_config())
            with open(config_dest, "w", encoding="utf-8") as fh:
                yaml.dump(cfg, fh, default_flow_style=False, allow_unicode=True)
            click.echo(f"✓ 生成默认配置: {config_dest}")
    else:
        click.echo(f"• 配置文件已存在: {config_dest}")

    # Initialise database
    try:
        from croncopilot.config.loader import ConfigLoader
        from croncopilot.storage.database import DatabaseManager

        loader = ConfigLoader(config_dest)
        config = loader.load()
        DatabaseManager(config.storage.db_path)
        click.echo(f"✓ 初始化数据库: {config.storage.db_path}")
    except FileNotFoundError as exc:
        click.echo(f"✗ 配置文件不存在: {exc}", err=True)
    except ValueError as exc:
        click.echo(f"✗ 配置参数无效: {exc}", err=True)
    except OSError as exc:
        click.echo(f"✗ 数据库初始化IO错误: {exc}", err=True)
    except Exception as exc:
        logger.exception("数据库初始化失败")
        click.echo(f"✗ 数据库初始化失败: {exc}", err=True)

    click.echo("\n初始化完成！使用 'croncopilot start' 启动调度器。")


# ------------------------------------------------------------------
# start
# ------------------------------------------------------------------


@cli.command()
@click.option("--daemon", "-d", is_flag=True, help="以守护进程模式运行")
@click.option("--foreground", "-f", is_flag=True, default=True, help="前台运行")
@click.pass_context
def start(ctx: click.Context, daemon: bool, foreground: bool) -> None:
    """启动调度器"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    click.echo("正在启动 CronCopilot ...")

    try:
        components = _init_components(config_path)
    except FileNotFoundError as exc:
        click.echo(f"✗ 配置文件不存在: {exc}", err=True)
        sys.exit(1)
    except ValueError as exc:
        click.echo(f"✗ 配置参数无效: {exc}", err=True)
        sys.exit(1)
    except OSError as exc:
        click.echo(f"✗ 初始化IO错误: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        logger.exception("初始化失败")
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    config = components["config"]
    loader = components["loader"]
    scheduler = components["scheduler"]
    health_checker = components["health_checker"]
    deadlock_detector = components["deadlock_detector"]

    # Daemon mode
    if daemon:
        from croncopilot.deploy.daemon import DaemonManager

        dm = DaemonManager(config.pid_file)
        dm.daemonize()
        click.echo(f"✓ 守护进程已启动 (PID: {os.getpid()})")
    else:
        # Write PID file even in foreground mode
        from croncopilot.deploy.daemon import DaemonManager

        dm = DaemonManager(config.pid_file)
        dm.write_pid()

    # 10. Start scheduler, health checker, deadlock detector
    try:
        scheduler.start()
        click.echo("✓ 调度器已启动")
    except Exception as exc:
        click.echo(f"✗ 调度器启动失败: {exc}", err=True)
        sys.exit(1)

    health_checker.start()
    logger.info("HealthChecker started")

    deadlock_detector.start()
    logger.info("DeadlockDetector started")

    # 12. Config hot-reload
    def _on_config_reload(new_config: Any) -> None:
        """Handle configuration file changes."""
        logger.info("Configuration reloaded, refreshing tasks ...")
        scheduler.reload_tasks()

    loader.start_watch(_on_config_reload)

    # 13. Signal handlers
    _shutdown_requested = False

    def _graceful_shutdown(signum: int, frame: Any) -> None:
        nonlocal _shutdown_requested
        if _shutdown_requested:
            return
        _shutdown_requested = True
        logger.info("Received signal %d, shutting down gracefully ...", signum)
        click.echo("\n正在关闭 CronCopilot ...")

        loader.stop_watch()
        health_checker.stop()
        deadlock_detector.stop()
        scheduler.stop()
        dm.remove_pid()

        click.echo("✓ CronCopilot 已停止")
        sys.exit(0)

    def _reload_config(signum: int, frame: Any) -> None:
        logger.info("Received SIGHUP, reloading configuration ...")
        try:
            new_config = loader.load()
            scheduler.reload_tasks()
            logger.info("Configuration reloaded via SIGHUP")
        except Exception:
            logger.exception("Failed to reload configuration via SIGHUP")

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _reload_config)

    click.echo(f"✓ CronCopilot 正在运行 (PID: {os.getpid()})")
    click.echo("  按 Ctrl+C 停止\n")

    # 14. Main loop
    try:
        while not _shutdown_requested:
            time.sleep(1)
    except KeyboardInterrupt:
        _graceful_shutdown(signal.SIGINT, None)


# ------------------------------------------------------------------
# stop
# ------------------------------------------------------------------


@cli.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """停止守护进程"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, _ = _init_light(config_path)
    except Exception:
        # Use default PID path if config can't load
        from croncopilot.config.schema import default_config

        config = default_config()
        config.pid_file = os.path.expanduser(config.pid_file)

    from croncopilot.deploy.daemon import DaemonManager

    dm = DaemonManager(config.pid_file)

    if not dm.is_running():
        click.echo("CronCopilot 未在运行")
        return

    pid = dm.get_pid()
    click.echo(f"正在停止 CronCopilot (PID: {pid}) ...")

    if dm.stop():
        click.echo("✓ CronCopilot 已停止")
    else:
        click.echo("✗ 停止失败，请手动检查进程", err=True)
        sys.exit(1)


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """查看运行状态"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 无法加载配置: {exc}", err=True)
        sys.exit(1)

    from croncopilot.deploy.daemon import DaemonManager

    dm = DaemonManager(config.pid_file)
    pid = dm.get_pid()

    if dm.is_running():
        click.echo(f"状态: 运行中 (PID: {pid})")
    else:
        click.echo("状态: 未运行")
        if pid is not None:
            click.echo(f"  (残留 PID 文件指向 PID {pid})")
        return

    # Show tasks
    tasks = db_manager.list_tasks()
    if tasks:
        click.echo(f"\n已注册任务: {len(tasks)}")
        click.echo(f"{'名称':<20} {'类型':<10} {'状态':<8} {'优先级':<6}")
        click.echo("-" * 50)
        for t in tasks:
            enabled_str = "启用" if t.enabled else "禁用"
            click.echo(
                f"{t.name:<20} {(t.schedule_type or 'cron'):<10} "
                f"{enabled_str:<8} {t.priority:<6}"
            )
    else:
        click.echo("\n暂无已注册任务")


# ======================================================================
# Task management sub-commands
# ======================================================================


@cli.group()
def task() -> None:
    """任务管理"""


@task.command("add")
@click.option("--name", "-n", required=True, help="任务名称")
@click.option("--script", "-s", required=True, help="脚本路径")
@click.option(
    "--schedule-type",
    "-t",
    type=click.Choice(["cron", "daily", "weekly", "monthly", "interval"]),
    required=True,
)
@click.option("--schedule", "-S", required=True, help="调度表达式")
@click.option("--priority", "-p", default=5, type=click.IntRange(1, 10), help="优先级 (1-10)")
@click.option("--timeout", default=3600, type=click.IntRange(1), help="超时时间(秒)")
@click.option('--max-retries', default=3, type=click.IntRange(0), help='最大重试次数')
@click.option('--max-instances', default=1, type=int, help='最大并发实例数，默认 1')
@click.option("--category", default="", help="分类")
@click.option("--description", default="", help="描述")
@click.option("--depends-on", multiple=True, help="依赖的任务名称")
@click.option(
    '--holiday-mode',
    type=click.Choice(['none', 'workday_only', 'holiday_only', 'skip_holiday', 'skip_workday']),
    default='none',
    help='节假日模式',
)
@click.pass_context
def task_add(
    ctx: click.Context,
    name: str,
    script: str,
    schedule_type: str,
    schedule: str,
    priority: int,
    timeout: int,
    max_retries: int,
    max_instances: int,
    category: str,
    description: str,
    depends_on: Tuple[str, ...],
    holiday_mode: str,
) -> None:
    """添加新任务"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    from croncopilot.core.task import TaskConfig, parse_schedule, task_config_to_record

    # Validate script path
    script_path = os.path.abspath(os.path.expanduser(script))
    if not os.path.isfile(script_path):
        click.echo(f"✗ 脚本文件不存在: {script_path}", err=True)
        sys.exit(1)

    # Validate schedule expression
    try:
        parse_schedule(schedule_type, schedule)
    except ValueError as exc:
        click.echo(f"✗ 调度表达式无效: {exc}", err=True)
        sys.exit(1)

    # Check for duplicate name
    existing = db_manager.get_task_by_name(name)
    if existing is not None:
        click.echo(f"✗ 任务 '{name}' 已存在", err=True)
        sys.exit(1)

    # Resolve dependency names to IDs
    dep_ids: list[str] = []
    for dep_name in depends_on:
        dep_record = db_manager.get_task_by_name(dep_name)
        if dep_record is None:
            click.echo(f"✗ 依赖任务 '{dep_name}' 不存在", err=True)
            sys.exit(1)
        dep_ids.append(dep_record.id)

    # Create TaskConfig
    task_config = TaskConfig(
        name=name,
        script_path=script_path,
        schedule_type=schedule_type,
        schedule_expr=schedule,
        priority=priority,
        timeout=timeout,
        max_retries=max_retries,
        max_instances=max_instances,
        category=category,
        description=description,
        dependencies=dep_ids,
        holiday_mode=holiday_mode,
    )

    # Save to database
    record = task_config_to_record(task_config)
    try:
        db_manager.add_task(record)
    except Exception as exc:
        click.echo(f"✗ 保存失败: {exc}", err=True)
        sys.exit(1)

    click.echo(f"✓ 任务 '{name}' 已添加 (ID: {task_config.task_id})")


@task.command("remove")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="强制删除")
@click.pass_context
def task_remove(ctx: click.Context, name: str, force: bool) -> None:
    """删除任务"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    record = db_manager.get_task_by_name(name)
    if record is None:
        click.echo(f"✗ 任务 '{name}' 不存在", err=True)
        sys.exit(1)

    if not force:
        click.confirm(f"确定要删除任务 '{name}'?", abort=True)

    try:
        db_manager.delete_task(record.id)
    except Exception as exc:
        click.echo(f"✗ 删除失败: {exc}", err=True)
        sys.exit(1)

    click.echo(f"✓ 任务 '{name}' 已删除")


@task.command("list")
@click.option("--category", "-c", default=None, help="按分类过滤")
@click.option("--status", "-s", default=None, help="按状态过滤")
@click.pass_context
def task_list(ctx: click.Context, category: Optional[str], status: Optional[str]) -> None:
    """列出所有任务"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    tasks = db_manager.list_tasks()

    # Apply filters
    if category:
        tasks = [t for t in tasks if (t.category or "") == category]
    if status:
        enabled_filter = status.lower() in ("enabled", "启用", "true")
        tasks = [t for t in tasks if t.enabled == enabled_filter]

    if not tasks:
        click.echo("暂无任务")
        return

    # Table output
    header = f"{'名称':<20} {'类型':<10} {'调度':<20} {'优先级':<6} {'状态':<6} {'节假日':<14} {'分类':<10}"
    click.echo(header)
    click.echo("-" * 90)
    for t in tasks:
        enabled_str = "启用" if t.enabled else "禁用"
        hm = getattr(t, 'holiday_mode', None) or 'none'
        click.echo(
            f"{t.name:<20} {(t.schedule_type or 'cron'):<10} "
            f"{(t.cron_expression or ''):<20} {t.priority:<6} "
            f"{enabled_str:<6} {hm:<14} {(t.category or ''):<10}"
        )

    click.echo(f"\n共 {len(tasks)} 个任务")


@task.command("run")
@click.argument("name")
@click.pass_context
def task_run(ctx: click.Context, name: str) -> None:
    """立即执行一次任务"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    from croncopilot.core.executor import TaskExecutor
    from croncopilot.core.task import record_to_task_config

    record = db_manager.get_task_by_name(name)
    if record is None:
        click.echo(f"✗ 任务 '{name}' 不存在", err=True)
        sys.exit(1)

    task_config = record_to_task_config(record)

    # Set up logging for execution
    setup_logging(
        log_dir=config.log.log_dir,
        level=config.log.level,
        max_days=config.log.max_days,
        json_format=config.log.json_format,
    )

    executor = TaskExecutor(max_workers=1, db_manager=db_manager)

    click.echo(f"正在执行任务 '{name}' ...")
    submitted = executor.submit(task_config, skip_holiday_check=True, trigger_type="manual")
    if not submitted:
        click.echo("✗ 任务提交失败（可能依赖未满足或并发限制）", err=True)
        executor.shutdown(wait=False)
        sys.exit(1)

    # Wait for completion
    click.echo("等待任务完成 ...")
    while executor.get_running_tasks():
        time.sleep(0.5)

    executor.shutdown(wait=True)

    # Check result
    latest = db_manager.get_latest_execution(task_config.task_id)
    if latest and latest.status == "success":
        click.echo(f"✓ 任务 '{name}' 执行成功 (耗时: {latest.duration:.2f}s)")
    elif latest:
        click.echo(f"✗ 任务 '{name}' 执行失败 (返回码: {latest.return_code})", err=True)
        if latest.error:
            click.echo(f"  错误: {latest.error[:500]}")
    else:
        click.echo("• 未能获取执行结果")


@task.command('history')
@click.argument('name')
@click.option('--days', '-d', default=30, help='查看最近 N 天的记录，默认 30 天')
@click.option('--limit', '-l', default=20, help='显示最近 N 条执行记录，默认 20 条')
@click.option('--stats-only', is_flag=True, help='仅显示统计摘要')
@click.pass_context
def task_history(ctx: click.Context, name: str, days: int, limit: int, stats_only: bool) -> None:
    """查看任务的历史执行记录和统计信息"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    # Look up task by name
    record = db_manager.get_task_by_name(name)
    if record is None:
        click.echo(f"✗ 任务 '{name}' 不存在", err=True)
        sys.exit(1)

    task_id = record.id

    # Header
    click.echo(f"任务: {record.name}")
    click.echo(f"调度: {record.schedule_type or 'cron'} | {record.cron_expression or '(未设置)'}")
    hm = getattr(record, 'holiday_mode', None) or 'none'
    if hm != 'none':
        click.echo(f"节假日模式: {hm}")
    click.echo()

    # ---- Statistics ----
    from croncopilot.monitor.metrics import MetricsCollector

    metrics = MetricsCollector(db_manager)
    stats = metrics.get_task_stats(task_id, days=days)

    total = stats["total_runs"]
    success_count = stats["success_count"]
    failure_count = stats["failure_count"]
    success_rate = stats["success_rate"]

    click.echo(f"📊 最近 {days} 天统计")
    click.echo("────────────────────────────")
    click.echo(f"总执行次数:  {total}")
    if total > 0:
        failure_rate = round(100.0 - float(success_rate), 1)
        click.echo(f"成功:        {success_count} ({success_rate}%)")
        click.echo(f"失败:        {failure_count} ({failure_rate}%)")
        click.echo(f"平均耗时:    {stats['avg_duration']}s")
        click.echo(f"最大耗时:    {stats['max_duration']}s")
        click.echo(f"P95 耗时:    {stats['p95_duration']}s")
        last_run = stats["last_run_time"]
        last_run_str = last_run.strftime("%Y-%m-%d %H:%M:%S") if last_run else "(无)"
        last_status = stats["last_status"] or "(无)"
        click.echo(f"最后执行:    {last_run_str}")
        click.echo(f"最后状态:    {last_status}")
    else:
        click.echo("暂无执行记录")

    if stats_only:
        return

    click.echo()

    # ---- Execution records ----
    from datetime import datetime, timedelta

    executions = db_manager.list_executions(task_id, limit=limit)
    cutoff = datetime.now() - timedelta(days=days)
    executions = [
        e for e in executions
        if e.start_time is not None and e.start_time >= cutoff
    ]

    if not executions:
        click.echo("暂无执行记录")
        return

    click.echo(f"📋 最近 {limit} 条执行记录")
    click.echo("────────────────────────────")
    click.echo(f"{'时间':<22}{'状态':<10}{'触发':<10}{'耗时':<10}{'返回码':<8}{'错误'}")

    status_map = {
        "success": ("成功", "green"),
        "failed": ("失败", "red"),
        "running": ("运行中", "yellow"),
        "pending": ("等待", "white"),
    }

    for e in executions:
        time_str = e.start_time.strftime("%Y-%m-%d %H:%M:%S") if e.start_time else "(未知)"
        label, color = status_map.get(e.status, (e.status, "white"))
        styled_status = click.style(f"{label:<8}", fg=color)
        trigger_label = getattr(e, 'trigger_type', None) or "scheduled"
        duration_str = f"{e.duration:.1f}s" if e.duration is not None else "-"
        rc_str = str(e.return_code) if e.return_code is not None else "-"
        error_str = (e.error[:40] + "...") if e.error and len(e.error) > 40 else (e.error or "-")
        click.echo(f"{time_str:<22}{styled_status}  {trigger_label:<10}{duration_str:<10}{rc_str:<8}{error_str}")


# ======================================================================
# Script management sub-commands
# ======================================================================


@cli.group()
def script() -> None:
    """脚本管理"""


@script.command("add")
@click.option("--path", "-p", required=True, help="脚本文件路径")
@click.option("--name", "-n", default=None, help="脚本名称（默认使用文件名）")
@click.option("--author", "-a", default="", help="作者")
@click.option("--description", "-d", default="", help="描述")
@click.option("--category", "-c", default="", help="分类")
@click.option("--venv", default="", help="虚拟环境路径")
@click.pass_context
def script_add(
    ctx: click.Context,
    path: str,
    name: Optional[str],
    author: str,
    description: str,
    category: str,
    venv: str,
) -> None:
    """注册脚本"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    from croncopilot.scripts.manager import ScriptManager

    mgr = ScriptManager(config.script, db_manager)

    try:
        metadata = mgr.register(
            script_path=path,
            name=name,
            author=author,
            description=description,
            category=category,
            venv_path=venv,
        )
    except FileNotFoundError as exc:
        click.echo(f"✗ {exc}", err=True)
        sys.exit(1)
    except ValueError as exc:
        click.echo(f"✗ {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"✗ 注册失败: {exc}", err=True)
        sys.exit(1)

    click.echo(f"✓ 脚本 '{metadata.name}' 已注册 (路径: {metadata.path})")


@script.command("remove")
@click.argument("name")
@click.option("--delete-file", is_flag=True, help="同时删除脚本文件")
@click.pass_context
def script_remove(ctx: click.Context, name: str, delete_file: bool) -> None:
    """注销脚本"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    from croncopilot.scripts.manager import ScriptManager

    mgr = ScriptManager(config.script, db_manager)

    try:
        mgr.unregister(name, delete_file=delete_file)
    except Exception as exc:
        click.echo(f"✗ 注销失败: {exc}", err=True)
        sys.exit(1)

    click.echo(f"✓ 脚本 '{name}' 已注销")


@script.command("list")
@click.option("--category", "-c", default=None, help="按分类过滤")
@click.pass_context
def script_list(ctx: click.Context, category: Optional[str]) -> None:
    """列出所有脚本"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    from croncopilot.scripts.manager import ScriptManager

    mgr = ScriptManager(config.script, db_manager)
    scripts = mgr.list_scripts(category=category)

    if not scripts:
        click.echo("暂无已注册脚本")
        return

    header = f"{'名称':<20} {'作者':<12} {'分类':<10} {'版本数':<6} {'路径'}"
    click.echo(header)
    click.echo("-" * 80)
    for s in scripts:
        click.echo(
            f"{s.name:<20} {s.author:<12} {(s.category or ''):<10} "
            f"{s.version_count:<6} {s.path}"
        )

    click.echo(f"\n共 {len(scripts)} 个脚本")


@script.command("info")
@click.argument("name")
@click.pass_context
def script_info(ctx: click.Context, name: str) -> None:
    """查看脚本详细信息和版本历史"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    from croncopilot.scripts.manager import ScriptManager

    mgr = ScriptManager(config.script, db_manager)
    info = mgr.get_info(name)

    if info is None:
        click.echo(f"✗ 脚本 '{name}' 不存在", err=True)
        sys.exit(1)

    click.echo(f"脚本名称:   {info.name}")
    click.echo(f"文件路径:   {info.path}")
    click.echo(f"作者:       {info.author or '(未设置)'}")
    click.echo(f"描述:       {info.description or '(未设置)'}")
    click.echo(f"分类:       {info.category or '(未设置)'}")
    click.echo(f"虚拟环境:   {info.venv_path or '(未设置)'}")
    click.echo(f"文件哈希:   {info.file_hash[:16]}..." if info.file_hash else "文件哈希:   (无)")
    click.echo(f"版本数:     {info.version_count}")
    click.echo(f"创建时间:   {info.created_at or '(未知)'}")
    click.echo(f"更新时间:   {info.updated_at or '(未知)'}")

    # Version history
    versions = mgr.get_versions(name)
    if versions:
        click.echo(f"\n版本历史 ({len(versions)} 个版本):")
        for v in versions:
            click.echo(f"  {v['timestamp']}  {v['hash']}  {v['version_path']}")


# ------------------------------------------------------------------
# health
# ------------------------------------------------------------------


@cli.command()
@click.pass_context
def health(ctx: click.Context) -> None:
    """执行系统健康检查"""
    config_path = ctx.obj.get("config_path") or _DEFAULT_CONFIG_PATH

    try:
        config, db_manager = _init_light(config_path)
    except Exception as exc:
        click.echo(f"✗ 初始化失败: {exc}", err=True)
        sys.exit(1)

    from croncopilot.monitor.metrics import MetricsCollector

    metrics = MetricsCollector(db_manager)
    sys_metrics = metrics.get_system_metrics()

    click.echo("系统健康检查")
    click.echo("=" * 40)

    items = [
        ("CPU 使用率", sys_metrics.get("cpu_percent"), config.recovery.cpu_threshold, "%"),
        ("内存使用率", sys_metrics.get("memory_percent"), config.recovery.memory_threshold, "%"),
        ("磁盘使用率", sys_metrics.get("disk_percent"), config.recovery.disk_threshold, "%"),
    ]

    all_healthy = True
    for label, value, threshold, unit in items:
        if value is None:
            click.echo(f"  {label}: 不可用")
            continue

        if value > threshold:
            status_icon = "✗"
            all_healthy = False
        else:
            status_icon = "✓"

        click.echo(f"  {status_icon} {label}: {value:.1f}{unit} (阈值: {threshold:.1f}{unit})")

    load_avg = sys_metrics.get("load_average")
    if load_avg is not None:
        click.echo(f"  • 负载均值: {load_avg:.2f}")

    click.echo()
    if all_healthy:
        click.echo("✓ 系统健康")
    else:
        click.echo("✗ 系统存在告警项")


# ======================================================================
# Entry point
# ======================================================================

if __name__ == "__main__":
    cli()
