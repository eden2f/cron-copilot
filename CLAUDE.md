# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

```bash
# Install in dev mode with test dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_executor.py

# Run a specific test
pytest tests/test_executor.py::test_function_name -v

# Run with coverage
pytest --cov=croncopilot --cov-report=term-missing
```

The CLI entry point is `croncopilot` (defined in `pyproject.toml` `[project.scripts]`, wired to `croncopilot.main:cli`). After `pip install -e .`, you can invoke it directly. All source lives under `src/croncopilot/`.

## Architecture

### Package layout

```
src/croncopilot/
├── main.py          # Click CLI (all commands defined here)
├── config/          # YAML loading, schema/dataclass defs, watchdog hot-reload
├── core/            # Scheduler (APScheduler wrapper), TaskExecutor (thread pool + priority heap), holiday checker, TaskConfig model
├── storage/         # SQLAlchemy ORM models + DatabaseManager CRUD
├── monitor/         # ExecutionTracker, MetricsCollector, AlertManager
├── recovery/        # RetryManager (exponential backoff), HealthChecker, DeadlockDetector
├── scripts/         # Script registration, version backup, syntax validation
├── logging/         # JSON-format logger setup + log rotation
└── deploy/          # DaemonManager (double-fork + PID file), ServiceGenerator (systemd/launchd)
```

### Component wiring (the callback chain)

`main.py:_init_components()` creates all subsystems and wires them together. The critical binding order matters:

1. **ExecutionTracker** is bound to **TaskExecutor** first (`tracker.bind_executor(executor)`)
2. **AlertManager** is bound to **ExecutionTracker** second (`alert_manager.bind_tracker(tracker)`)
3. **RetryManager** is bound to **TaskExecutor** last (`retry_manager.bind_executor(executor)`)

Each `bind_*` call wraps the executor's `on_task_complete` hook, so the execution order at task completion is: RetryManager → AlertManager → ExecutionTracker (innermost). RetryManager sees the result first and decides whether to retry; AlertManager checks failure thresholds; ExecutionTracker persists the record.

### Task execution flow

1. APScheduler triggers `SchedulerManager._task_wrapper(task_id)` → holiday check → `executor.submit(task_config)`
2. `TaskExecutor.submit()` checks dependencies (via DB), checks `max_instances`, pushes onto a `heapq` priority heap
3. `_process_queue()` drains the heap, acquiring a `Semaphore(max_workers)` per slot, submits to `ThreadPoolExecutor`
4. Worker thread spawns script via `subprocess.Popen` (isolated env, venv support), captures stdout/stderr, enforces timeout
5. On completion, `on_task_complete` callback chain fires (tracker records to DB, alert checks thresholds, retry schedules re-submit if needed)

### Key design details

- **Hot-reload**: CLI `task add/update/remove` writes to DB then sends `SIGHUP` via `_notify_daemon_reload()` to the running daemon's PID. The daemon's signal handler calls `scheduler.reload_tasks()` which removes all APScheduler jobs and re-loads from DB. Config file changes are also watched via watchdog.
- **Single-instance protection**: On `start`, `DaemonManager.stop_existing_instances()` checks the PID file and scans `ps aux` for orphan croncopilot processes, killing any it finds before proceeding.
- **Holiday checking**: Happens in two places — `SchedulerManager._task_wrapper()` for scheduled triggers, and `TaskExecutor.submit()` as a secondary guard. Manual runs (`task run`, `run_task_now`) pass `skip_holiday_check=True`.
- **TaskRecord vs TaskConfig**: `TaskRecord` is the SQLAlchemy ORM model (database). `TaskConfig` is a plain dataclass (in-memory). Convert between them with `task_config_to_record()` / `record_to_task_config()` in `core/task.py`.
- **Database migration**: `DatabaseManager.__init__()` does lightweight auto-migration by inspecting existing columns and running `ALTER TABLE` for missing columns (see `holiday_mode`, `trigger_type`). This is not Alembic — it's inline and additive only.
- **Subprocess isolation**: Scripts run as child processes with a minimal environment (only `PATH`, `HOME`, `LANG`, etc. forwarded). Sensitive patterns (`password=`, `api_key=`, `token=`) in stdout/stderr are redacted via `_sanitize_output()`.
- **Daemon mode**: Classic Unix double-fork in `DaemonManager.daemonize()`. This means the project is Unix-only (no Windows support without WSL2).
- **Config schema**: All config sections are dataclasses in `config/schema.py`. `ConfigLoader.load()` deep-merges YAML overrides onto defaults, then validates ranges. `AppConfig` is the top-level object passed throughout the system.

### Tests

Tests live in `tests/` and use pytest. `conftest.py` provides `tmp_db` (in-memory SQLite via tempfile), `default_config`, `sample_task_config`, and script fixtures (`sample_script`, `failing_script`, `slow_script`). The test files mirror the source package structure: `test_config.py`, `test_scheduler.py`, `test_executor.py`, `test_monitor.py`, `test_recovery.py`, `test_holiday.py`, `test_scripts.py`, `test_daemon.py`, `test_service.py`, `test_main_cli.py`.
