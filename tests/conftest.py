import pytest
import tempfile
import os


@pytest.fixture
def tmp_dir():
    """临时目录"""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def tmp_db(tmp_dir):
    """临时数据库"""
    from pycronguard.storage.database import DatabaseManager
    db_path = os.path.join(tmp_dir, "test.db")
    return DatabaseManager(db_path)


@pytest.fixture
def default_config():
    """默认配置"""
    from pycronguard.config.schema import default_config
    return default_config()


@pytest.fixture
def sample_task_config():
    """示例任务配置"""
    from pycronguard.core.task import TaskConfig
    import uuid
    return TaskConfig(
        task_id=str(uuid.uuid4()),
        name="test_task",
        script_path="/tmp/test_script.py",
        schedule_type="daily",
        schedule_expr="08:00",
        priority=5,
        max_retries=3,
        timeout=60,
    )


# 还需要创建用于测试的简单 Python 脚本 fixture
@pytest.fixture
def sample_script(tmp_dir):
    """创建一个用于测试的简单脚本"""
    script_path = os.path.join(tmp_dir, "test_script.py")
    with open(script_path, "w") as f:
        f.write('import sys\nprint("Hello from test script")\nsys.exit(0)\n')
    return script_path


@pytest.fixture
def failing_script(tmp_dir):
    """创建一个会失败的测试脚本"""
    script_path = os.path.join(tmp_dir, "fail_script.py")
    with open(script_path, "w") as f:
        f.write('import sys\nprint("Error!", file=sys.stderr)\nsys.exit(1)\n')
    return script_path


@pytest.fixture
def slow_script(tmp_dir):
    """创建一个耗时较长的测试脚本"""
    script_path = os.path.join(tmp_dir, "slow_script.py")
    with open(script_path, "w") as f:
        f.write('import time\ntime.sleep(10)\nprint("Done")\n')
    return script_path
