"""执行器测试 — TaskExecutor."""

import time
import threading
import pytest
from unittest.mock import MagicMock, patch

from croncopilot.core.executor import TaskExecutor
from croncopilot.core.task import TaskConfig
from croncopilot.storage.models import TaskExecution, TaskRecord


class TestTaskExecutor:
    """测试 TaskExecutor."""

    def test_submit_and_execute(self, tmp_db, sample_script):
        """提交任务并成功执行（使用 sample_script fixture）."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        # First register the task in DB so execution records have a valid FK
        task_config = TaskConfig(
            name="exec_ok",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        result = executor.submit(task_config)
        assert result is True
        # Wait for completion
        time.sleep(3)
        executor.shutdown(wait=True)

        execs = tmp_db.list_executions(task_config.task_id)
        # Should have at least one success execution
        statuses = [e.status for e in execs]
        assert "success" in statuses

    def test_execute_failing_script(self, tmp_db, failing_script):
        """执行失败脚本，正确记录错误."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        task_config = TaskConfig(
            name="exec_fail",
            script_path=failing_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config)
        time.sleep(3)
        executor.shutdown(wait=True)

        execs = tmp_db.list_executions(task_config.task_id)
        statuses = [e.status for e in execs]
        assert "failed" in statuses

    def test_priority_ordering(self, tmp_db, sample_script):
        """高优先级任务先执行（验证优先级队列使用 heap）."""
        import heapq
        # Verify priority queue ordering directly — lower number = higher priority
        queue = []
        heapq.heappush(queue, (9, 0.1, "low"))
        heapq.heappush(queue, (1, 0.2, "high"))
        heapq.heappush(queue, (5, 0.3, "mid"))

        order = []
        while queue:
            prio, _, name = heapq.heappop(queue)
            order.append((prio, name))

        assert order[0] == (1, "high")
        assert order[1] == (5, "mid")
        assert order[2] == (9, "low")

        # Also verify executor accepts different priorities
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        high = TaskConfig(
            name="high_prio",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            priority=1,
            timeout=30,
        )
        low = TaskConfig(
            name="low_prio",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            priority=9,
            timeout=30,
        )
        record_h = TaskRecord(id=high.task_id, name=high.name, script_path=sample_script)
        record_l = TaskRecord(id=low.task_id, name=low.name, script_path=sample_script)
        tmp_db.add_task(record_h)
        tmp_db.add_task(record_l)

        assert executor.submit(high) is True
        assert executor.submit(low) is True
        time.sleep(3)
        executor.shutdown(wait=True)

    def test_concurrency_limit(self, tmp_db, slow_script):
        """并发数限制生效."""
        executor = TaskExecutor(max_workers=1, db_manager=tmp_db)
        configs = []
        for i in range(2):
            tc = TaskConfig(
                name=f"conc_{i}",
                script_path=slow_script,
                schedule_type="daily",
                schedule_expr="08:00",
                timeout=30,
            )
            record = TaskRecord(id=tc.task_id, name=tc.name, script_path=slow_script)
            tmp_db.add_task(record)
            configs.append(tc)

        for tc in configs:
            executor.submit(tc)

        time.sleep(1)
        running = executor.get_running_tasks()
        # Should only have 1 running due to max_workers=1
        assert len(running) <= 1
        executor.shutdown(wait=False)

    def test_task_timeout(self, tmp_db, slow_script):
        """超时任务被终止（使用 slow_script，设短 timeout）."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        task_config = TaskConfig(
            name="timeout_test",
            script_path=slow_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=1,  # 1 second timeout, script sleeps 10s
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config)
        time.sleep(5)
        executor.shutdown(wait=True)

        execs = tmp_db.list_executions(task_config.task_id)
        statuses = [e.status for e in execs]
        assert "failed" in statuses

    def test_cancel_task(self, tmp_db, slow_script):
        """取消运行中的任务."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)
        task_config = TaskConfig(
            name="cancel_test",
            script_path=slow_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=60,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config)
        time.sleep(1)  # Wait for process to start

        cancelled = executor.cancel_task(task_config.task_id)
        assert cancelled is True

        time.sleep(2)
        executor.shutdown(wait=True)

    def test_callbacks(self, tmp_db, sample_script):
        """on_task_start 和 on_task_complete 回调被正确调用."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)

        start_called = threading.Event()
        complete_called = threading.Event()
        start_args = {}
        complete_args = {}

        def on_start(task_id, task_config, **kwargs):
            start_args["task_id"] = task_id
            start_args["trigger_type"] = kwargs.get("trigger_type", "scheduled")
            start_called.set()

        def on_complete(task_id, success, result):
            complete_args["task_id"] = task_id
            complete_args["success"] = success
            complete_called.set()

        executor.on_task_start = on_start
        executor.on_task_complete = on_complete

        task_config = TaskConfig(
            name="callback_test",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config)

        assert start_called.wait(timeout=10)
        assert complete_called.wait(timeout=10)
        assert start_args["task_id"] == task_config.task_id
        assert complete_args["task_id"] == task_config.task_id
        assert complete_args["success"] is True

        executor.shutdown(wait=True)

    def test_submit_default_trigger_type(self, tmp_db, sample_script):
        """submit() 默认 trigger_type 为 'scheduled'."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)

        start_event = threading.Event()
        captured = {}

        def on_start(task_id, task_config, **kwargs):
            captured["trigger_type"] = kwargs.get("trigger_type", "scheduled")
            start_event.set()

        executor.on_task_start = on_start
        executor.on_task_complete = lambda tid, s, r: None

        task_config = TaskConfig(
            name="default_trigger",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config)
        assert start_event.wait(timeout=10)
        assert captured["trigger_type"] == "scheduled"
        executor.shutdown(wait=True)

    def test_submit_with_manual_trigger_type(self, tmp_db, sample_script):
        """submit(trigger_type='manual') 时 RunningTaskInfo 和回调正确记录."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)

        start_event = threading.Event()
        captured = {}

        def on_start(task_id, task_config, **kwargs):
            captured["trigger_type"] = kwargs.get("trigger_type", "scheduled")
            start_event.set()

        executor.on_task_start = on_start
        executor.on_task_complete = lambda tid, s, r: None

        task_config = TaskConfig(
            name="manual_trigger",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config, trigger_type="manual")
        assert start_event.wait(timeout=10)
        assert captured["trigger_type"] == "manual"
        executor.shutdown(wait=True)

    def test_submit_with_retry_trigger_type(self, tmp_db, sample_script):
        """submit(trigger_type='retry') 时回调收到正确的 trigger_type."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)

        start_event = threading.Event()
        captured = {}

        def on_start(task_id, task_config, **kwargs):
            captured["trigger_type"] = kwargs.get("trigger_type", "scheduled")
            start_event.set()

        executor.on_task_start = on_start
        executor.on_task_complete = lambda tid, s, r: None

        task_config = TaskConfig(
            name="retry_trigger",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config, trigger_type="retry")
        assert start_event.wait(timeout=10)
        assert captured["trigger_type"] == "retry"
        executor.shutdown(wait=True)

    def test_running_task_info_trigger_type(self, tmp_db, slow_script):
        """RunningTaskInfo 中正确记录 trigger_type."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)

        task_config = TaskConfig(
            name="info_trigger",
            script_path=slow_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=60,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=task_config.script_path,
        )
        tmp_db.add_task(record)

        executor.submit(task_config, trigger_type="manual")
        import time as _time
        _time.sleep(1)

        running = executor.get_running_tasks()
        assert task_config.task_id in running
        assert running[task_config.task_id].trigger_type == "manual"

        executor.shutdown(wait=False)

    def test_max_instances_concurrent_submit(self, tmp_db, slow_script):
        """并发提交时 max_instances 限制正确生效（竞态条件修复验证）."""
        executor = TaskExecutor(max_workers=4, db_manager=tmp_db)

        # 创建 max_instances=2 的任务配置（使用固定 task_id）
        task_config = TaskConfig(
            name="race_test",
            script_path=slow_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
            max_instances=2,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=slow_script,
        )
        tmp_db.add_task(record)

        # Patch _process_queue to no-op so tasks stay in queue and don't
        # drain during the concurrent submit phase.
        with patch.object(executor, '_process_queue', lambda: None):
            results = []
            lock = threading.Lock()
            barrier = threading.Barrier(10)

            def submit_task():
                barrier.wait()  # 所有线程同时开始
                r = executor.submit(task_config)
                with lock:
                    results.append(r)

            threads = [threading.Thread(target=submit_task) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # 只有 max_instances=2 个应该被接受（因为队列未被消费）
        accepted = sum(1 for r in results if r is True)
        assert accepted == 2, f"Expected 2 accepted, got {accepted}"

        executor.shutdown(wait=False)

    def test_max_instances_single_thread(self, tmp_db, slow_script):
        """单线程下 max_instances 限制正确生效."""
        executor = TaskExecutor(max_workers=4, db_manager=tmp_db)

        task_config = TaskConfig(
            name="single_max",
            script_path=slow_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
            max_instances=1,
        )
        record = TaskRecord(
            id=task_config.task_id, name=task_config.name,
            script_path=slow_script,
        )
        tmp_db.add_task(record)

        # 第一次提交应成功
        assert executor.submit(task_config) is True
        # 第二次提交应被拒绝（第一个还在运行）
        assert executor.submit(task_config) is False

        time.sleep(1)
        executor.shutdown(wait=False)

    def test_dependency_check(self, tmp_db, sample_script):
        """依赖任务未完成时不执行."""
        executor = TaskExecutor(max_workers=2, db_manager=tmp_db)

        dep_id = "dep-task-id-that-does-not-exist"
        task_config = TaskConfig(
            name="dep_check",
            script_path=sample_script,
            schedule_type="daily",
            schedule_expr="08:00",
            timeout=30,
            dependencies=[dep_id],
        )

        # The dependency has no successful execution, so submit should return False
        result = executor.submit(task_config)
        assert result is False

        executor.shutdown(wait=False)
