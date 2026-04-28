"""守护进程管理测试 — DaemonManager."""

import os
import signal
import subprocess
import pytest
from unittest.mock import patch, MagicMock, mock_open, call

from croncopilot.deploy.daemon import DaemonManager


class TestDaemonManagerInit:
    """测试 DaemonManager 初始化."""

    def test_init_expands_home_path(self):
        """初始化时展开 ~ 路径."""
        dm = DaemonManager("~/croncopilot.pid")
        expected = os.path.expanduser("~/croncopilot.pid")
        assert dm._pid_file == expected

    def test_init_absolute_path(self):
        """绝对路径不做额外变换."""
        dm = DaemonManager("/var/run/croncopilot.pid")
        assert dm._pid_file == "/var/run/croncopilot.pid"

    def test_init_relative_path(self):
        """相对路径保持不变."""
        dm = DaemonManager("run/croncopilot.pid")
        assert dm._pid_file == "run/croncopilot.pid"


class TestDaemonManagerGetPid:
    """测试 get_pid 方法."""

    def test_get_pid_file_exists(self, tmp_dir):
        """PID 文件存在且内容有效时返回整数."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("12345")
        dm = DaemonManager(pid_file)
        assert dm.get_pid() == 12345

    def test_get_pid_file_not_exists(self, tmp_dir):
        """PID 文件不存在时返回 None."""
        pid_file = os.path.join(tmp_dir, "nonexistent.pid")
        dm = DaemonManager(pid_file)
        assert dm.get_pid() is None

    def test_get_pid_invalid_content(self, tmp_dir):
        """PID 文件内容无效时返回 None."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("not_a_number")
        dm = DaemonManager(pid_file)
        assert dm.get_pid() is None

    def test_get_pid_empty_file(self, tmp_dir):
        """PID 文件为空时返回 None."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("")
        dm = DaemonManager(pid_file)
        assert dm.get_pid() is None


class TestDaemonManagerIsRunning:
    """测试 is_running 方法."""

    def test_is_running_process_alive(self, tmp_dir):
        """进程存活时返回 True."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill") as mock_kill:
            mock_kill.return_value = None
            assert dm.is_running() is True
            mock_kill.assert_called_once_with(12345, 0)

    def test_is_running_process_not_found(self, tmp_dir):
        """进程不存在时返回 False."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "get_pid", return_value=99999), \
             patch("os.kill", side_effect=ProcessLookupError):
            assert dm.is_running() is False

    def test_is_running_permission_denied(self, tmp_dir):
        """无权限但进程存在时返回 True."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "get_pid", return_value=1), \
             patch("os.kill", side_effect=PermissionError):
            assert dm.is_running() is True

    def test_is_running_no_pid(self, tmp_dir):
        """无 PID 时返回 False."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "get_pid", return_value=None):
            assert dm.is_running() is False

    def test_is_running_os_error(self, tmp_dir):
        """其他 OSError 时返回 False."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill", side_effect=OSError("unexpected")):
            assert dm.is_running() is False


class TestDaemonManagerWritePid:
    """测试 write_pid 方法."""

    def test_write_pid_creates_file(self, tmp_dir):
        """写入 PID 文件并创建父目录."""
        pid_file = os.path.join(tmp_dir, "sub", "deep", "test.pid")
        dm = DaemonManager(pid_file)
        dm.write_pid()

        assert os.path.isfile(pid_file)
        with open(pid_file, "r") as f:
            assert int(f.read()) == os.getpid()

    def test_write_pid_existing_dir(self, tmp_dir):
        """目录已存在时直接写入."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)
        dm.write_pid()

        assert os.path.isfile(pid_file)
        with open(pid_file, "r") as f:
            assert int(f.read()) == os.getpid()


class TestDaemonManagerRemovePid:
    """测试 remove_pid 方法."""

    def test_remove_pid_success(self, tmp_dir):
        """成功删除 PID 文件."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("12345")

        dm = DaemonManager(pid_file)
        dm.remove_pid()
        assert not os.path.isfile(pid_file)

    def test_remove_pid_file_not_exists(self, tmp_dir):
        """PID 文件不存在时不报错."""
        pid_file = os.path.join(tmp_dir, "nonexistent.pid")
        dm = DaemonManager(pid_file)
        dm.remove_pid()  # Should not raise

    def test_remove_pid_permission_error(self, tmp_dir):
        """权限错误时记录警告但不抛异常."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("12345")

        dm = DaemonManager(pid_file)
        with patch("os.path.isfile", return_value=True), \
             patch("os.remove", side_effect=OSError("Permission denied")):
            dm.remove_pid()  # Should not raise


class TestDaemonManagerDaemonize:
    """测试 daemonize 方法."""

    def _mock_fileno(self, n):
        """创建返回固定 fd 的 fileno mock."""
        m = MagicMock()
        m.fileno.return_value = n
        return m

    @patch("croncopilot.deploy.daemon.logger")
    @patch("atexit.register")
    @patch("os.close")
    @patch("os.dup2")
    @patch("os.open", return_value=3)
    @patch("os.umask")
    @patch("os.setsid")
    @patch("os.fork")
    def test_daemonize_success(self, mock_fork, mock_setsid, mock_umask,
                                mock_open, mock_dup2, mock_close,
                                mock_atexit, mock_logger):
        """双 fork 成功完成守护进程化."""
        mock_fork.side_effect = [0, 0]

        dm = DaemonManager("/tmp/test.pid")
        with patch.object(dm, "write_pid"), \
             patch("sys.stdin", self._mock_fileno(0)), \
             patch("sys.stdout", self._mock_fileno(1)), \
             patch("sys.stderr", self._mock_fileno(2)):
            dm.daemonize()

        assert mock_fork.call_count == 2
        mock_setsid.assert_called_once()
        mock_umask.assert_called_once_with(0)
        assert mock_dup2.call_count == 3
        mock_atexit.assert_called_once_with(dm.remove_pid)

    @patch("os.fork")
    def test_daemonize_first_fork_parent_exits(self, mock_fork):
        """第一次 fork 父进程退出."""
        mock_fork.return_value = 100  # parent
        dm = DaemonManager("/tmp/test.pid")
        with pytest.raises(SystemExit) as exc_info:
            dm.daemonize()
        assert exc_info.value.code == 0

    @patch("os.fork")
    def test_daemonize_first_fork_failure(self, mock_fork):
        """第一次 fork 失败时退出."""
        mock_fork.side_effect = OSError("fork failed")
        dm = DaemonManager("/tmp/test.pid")
        with pytest.raises(SystemExit) as exc_info:
            dm.daemonize()
        assert exc_info.value.code == 1

    @patch("os.umask")
    @patch("os.setsid")
    @patch("os.fork")
    def test_daemonize_second_fork_parent_exits(self, mock_fork, mock_setsid,
                                                  mock_umask):
        """第二次 fork 父进程退出."""
        mock_fork.side_effect = [0, 200]  # child, then parent
        dm = DaemonManager("/tmp/test.pid")
        with pytest.raises(SystemExit) as exc_info:
            dm.daemonize()
        assert exc_info.value.code == 0

    @patch("os.umask")
    @patch("os.setsid")
    @patch("os.fork")
    def test_daemonize_second_fork_failure(self, mock_fork, mock_setsid,
                                            mock_umask):
        """第二次 fork 失败时退出."""
        mock_fork.side_effect = [0, OSError("fork failed")]
        dm = DaemonManager("/tmp/test.pid")
        with pytest.raises(SystemExit) as exc_info:
            dm.daemonize()
        assert exc_info.value.code == 1

    @patch("croncopilot.deploy.daemon.logger")
    @patch("atexit.register")
    @patch("os.close")
    @patch("os.dup2")
    @patch("os.open", return_value=5)
    @patch("os.umask")
    @patch("os.setsid")
    @patch("os.fork", side_effect=[0, 0])
    def test_daemonize_fd_redirect(self, mock_fork, mock_setsid, mock_umask,
                                     mock_open, mock_dup2, mock_close,
                                     mock_atexit, mock_logger):
        """标准文件描述符重定向到 /dev/null."""
        dm = DaemonManager("/tmp/test.pid")
        with patch.object(dm, "write_pid"), \
             patch("sys.stdin", self._mock_fileno(0)), \
             patch("sys.stdout", self._mock_fileno(1)), \
             patch("sys.stderr", self._mock_fileno(2)):
            dm.daemonize()

        mock_open.assert_called_once_with(os.devnull, os.O_RDWR)
        assert mock_dup2.call_count == 3
        mock_close.assert_called_once_with(5)

    @patch("croncopilot.deploy.daemon.logger")
    @patch("atexit.register")
    @patch("os.close")
    @patch("os.dup2")
    @patch("os.open", return_value=3)
    @patch("os.umask")
    @patch("os.setsid")
    @patch("os.fork", side_effect=[0, 0])
    def test_daemonize_writes_pid_and_registers_atexit(self, mock_fork,
                                                         mock_setsid, mock_umask,
                                                         mock_open, mock_dup2,
                                                         mock_close,
                                                         mock_atexit, mock_logger):
        """守护进程化后写入 PID 并注册 atexit."""
        dm = DaemonManager("/tmp/test.pid")
        with patch.object(dm, "write_pid") as mock_write_pid, \
             patch("sys.stdin", self._mock_fileno(0)), \
             patch("sys.stdout", self._mock_fileno(1)), \
             patch("sys.stderr", self._mock_fileno(2)):
            dm.daemonize()
            mock_write_pid.assert_called_once()
        mock_atexit.assert_called_once_with(dm.remove_pid)


class TestDaemonManagerStop:
    """测试 stop 方法."""

    def test_stop_no_pid(self, tmp_dir):
        """无 PID 文件时返回 False."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)
        assert dm.stop() is False

    def test_stop_sigterm_success(self, tmp_dir):
        """SIGTERM 后进程正常退出."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == 0:
                raise ProcessLookupError

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill", side_effect=mock_kill), \
             patch.object(dm, "remove_pid") as mock_remove:
            result = dm.stop()

        assert result is True
        assert kill_calls[0] == (12345, signal.SIGTERM)
        mock_remove.assert_called_once()

    def test_stop_process_already_terminated(self, tmp_dir):
        """发送 SIGTERM 时进程已终止."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill", side_effect=ProcessLookupError), \
             patch.object(dm, "remove_pid") as mock_remove:
            result = dm.stop()

        assert result is True
        mock_remove.assert_called_once()

    def test_stop_sigterm_oserror(self, tmp_dir):
        """发送 SIGTERM 时 OSError 返回 False."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill", side_effect=OSError("not permitted")):
            result = dm.stop()

        assert result is False

    def test_stop_timeout_sigkill(self, tmp_dir):
        """SIGTERM 超时后发送 SIGKILL."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == 0:
                return None  # process still alive
            if sig == signal.SIGKILL:
                return None

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill", side_effect=mock_kill), \
             patch("time.sleep"), \
             patch.object(dm, "remove_pid") as mock_remove:
            result = dm.stop()

        assert result is True
        # Should have sent SIGTERM and SIGKILL
        sigs_sent = [sig for _, sig in kill_calls if sig != 0]
        assert signal.SIGTERM in sigs_sent
        assert signal.SIGKILL in sigs_sent
        mock_remove.assert_called_once()

    def test_stop_sigkill_oserror(self, tmp_dir):
        """SIGKILL 发送失败返回 False."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        def mock_kill(pid, sig):
            if sig == signal.SIGTERM:
                return None
            if sig == 0:
                return None  # always alive
            if sig == signal.SIGKILL:
                raise OSError("kill failed")

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill", side_effect=mock_kill), \
             patch("time.sleep"):
            result = dm.stop()

        assert result is False

    def test_stop_sigkill_process_already_gone(self, tmp_dir):
        """SIGKILL 时进程已退出."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        def mock_kill(pid, sig):
            if sig == signal.SIGTERM:
                return None
            if sig == 0:
                return None  # alive during wait
            if sig == signal.SIGKILL:
                raise ProcessLookupError

        with patch.object(dm, "get_pid", return_value=12345), \
             patch("os.kill", side_effect=mock_kill), \
             patch("time.sleep"), \
             patch.object(dm, "remove_pid") as mock_remove:
            result = dm.stop()

        assert result is True
        mock_remove.assert_called_once()


class TestDaemonManagerSignalHandlers:
    """测试 setup_signal_handlers 方法."""

    def test_setup_signal_handlers_registers_all(self):
        """注册 SIGTERM、SIGINT、SIGHUP 处理器."""
        dm = DaemonManager("/tmp/test.pid")
        shutdown_cb = MagicMock()
        reload_cb = MagicMock()

        with patch("signal.signal") as mock_signal:
            dm.setup_signal_handlers(shutdown_cb, reload_cb)

        calls = mock_signal.call_args_list
        registered_signals = [c[0][0] for c in calls]
        assert signal.SIGTERM in registered_signals
        assert signal.SIGINT in registered_signals
        if hasattr(signal, "SIGHUP"):
            assert signal.SIGHUP in registered_signals

    def test_signal_handler_calls_shutdown_callback(self):
        """SIGTERM/SIGINT 处理器调用 shutdown 回调."""
        dm = DaemonManager("/tmp/test.pid")
        shutdown_cb = MagicMock()
        reload_cb = MagicMock()

        handlers = {}

        def capture_signal(sig, handler):
            handlers[sig] = handler

        with patch("signal.signal", side_effect=capture_signal):
            dm.setup_signal_handlers(shutdown_cb, reload_cb)

        # Invoke SIGTERM handler
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        shutdown_cb.assert_called_once()

        # Invoke SIGINT handler
        shutdown_cb.reset_mock()
        handlers[signal.SIGINT](signal.SIGINT, None)
        shutdown_cb.assert_called_once()

    def test_signal_handler_calls_reload_callback(self):
        """SIGHUP 处理器调用 reload 回调."""
        if not hasattr(signal, "SIGHUP"):
            pytest.skip("SIGHUP not available on this platform")

        dm = DaemonManager("/tmp/test.pid")
        shutdown_cb = MagicMock()
        reload_cb = MagicMock()

        handlers = {}

        def capture_signal(sig, handler):
            handlers[sig] = handler

        with patch("signal.signal", side_effect=capture_signal):
            dm.setup_signal_handlers(shutdown_cb, reload_cb)

        handlers[signal.SIGHUP](signal.SIGHUP, None)
        reload_cb.assert_called_once()


class TestDaemonManagerKillPid:
    """测试 _kill_pid 方法."""

    def test_kill_pid_already_gone(self, tmp_dir):
        """进程已经不存在时直接返回 True."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        with patch("os.kill", side_effect=ProcessLookupError):
            assert dm._kill_pid(12345) is True

    def test_kill_pid_sigterm_succeeds(self, tmp_dir):
        """SIGTERM 后进程正常退出."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        calls = []

        def fake_kill(pid, sig):
            calls.append(sig)
            if sig == 0:
                raise ProcessLookupError

        with patch("os.kill", side_effect=fake_kill), \
             patch("time.monotonic", side_effect=[0, 0.1, 1]):
            assert dm._kill_pid(12345) is True

    def test_kill_pid_escalates_to_sigkill(self, tmp_dir):
        """SIGTERM 超时后升级为 SIGKILL."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))

        # monotonic: start, then always past deadline so loop exits immediately
        monotonic_values = iter([0.0, 100.0])

        def fake_kill(pid, sig):
            pass  # always succeeds, process "alive"

        with patch("os.kill", side_effect=fake_kill) as mock_kill, \
             patch("time.monotonic", side_effect=monotonic_values), \
             patch("time.sleep"):
            result = dm._kill_pid(12345, timeout=5.0)

        assert result is True
        # Should have sent SIGTERM then SIGKILL
        sigs = [c[0][1] for c in mock_kill.call_args_list]
        assert signal.SIGTERM in sigs
        assert signal.SIGKILL in sigs

    def test_kill_pid_oserror_on_sigterm(self, tmp_dir):
        """SIGTERM 发送失败返回 False."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        with patch("os.kill", side_effect=OSError("not permitted")):
            assert dm._kill_pid(12345) is False


class TestFindOtherCroncopilotPids:
    """测试 _find_other_croncopilot_pids 方法."""

    def test_finds_other_pids(self, tmp_dir):
        """从 ps 输出中找到其他 croncopilot 进程."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        ps_output = (
            "USER       PID  ...\n"
            f"user     {os.getpid()}  0.0  0.0  0  0 ?  S  00:00  0:00 python -m croncopilot start\n"
            "user     99999  0.0  0.0  0  0 ?  S  00:00  0:00 python -m croncopilot start --daemon\n"
        )
        with patch("subprocess.check_output", return_value=ps_output):
            pids = dm._find_other_croncopilot_pids()
        assert 99999 in pids
        assert os.getpid() not in pids

    def test_excludes_grep_lines(self, tmp_dir):
        """排除 grep 自身的行."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        ps_output = (
            "USER       PID  ...\n"
            "user     88888  0.0  0.0  0  0 ?  S  00:00  0:00 grep croncopilot\n"
        )
        with patch("subprocess.check_output", return_value=ps_output):
            pids = dm._find_other_croncopilot_pids()
        assert pids == []

    def test_handles_subprocess_error(self, tmp_dir):
        """ps 命令失败时返回空列表."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        with patch("subprocess.check_output", side_effect=subprocess.SubprocessError):
            assert dm._find_other_croncopilot_pids() == []

    def test_ignores_editor_processes(self, tmp_dir):
        """编辑器进程（如 vim）不会被误识别为 CronCopilot 进程."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        ps_output = (
            "USER       PID  ..\n"
            "user     55555  0.0  0.0  0  0 ?  S  00:00  0:00 vim /path/to/croncopilot/daemon.py\n"
            "user     55556  0.0  0.0  0  0 ?  S  00:00  0:00 python -m pdb src/croncopilot/main.py\n"
            "user     55557  0.0  0.0  0  0 ?  S  00:00  0:00 code /home/user/croncopilot/deploy/daemon.py\n"
        )
        with patch("subprocess.check_output", return_value=ps_output):
            pids = dm._find_other_croncopilot_pids()
        assert pids == []

    def test_ignores_non_start_commands(self, tmp_dir):
        """croncopilot task run 等非 start 命令不会被误杀."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        ps_output = (
            "USER       PID  ..\n"
            "user     66666  0.0  0.0  0  0 ?  S  00:00  0:00 croncopilot task run my_task\n"
            "user     66667  0.0  0.0  0  0 ?  S  00:00  0:00 croncopilot status\n"
            "user     66668  0.0  0.0  0  0 ?  S  00:00  0:00 python -m croncopilot task list\n"
        )
        with patch("subprocess.check_output", return_value=ps_output):
            pids = dm._find_other_croncopilot_pids()
        assert pids == []

    def test_matches_cli_start_variants(self, tmp_dir):
        """CLI 直接启动的各种变体都能被识别."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        ps_output = (
            "USER       PID  ..\n"
            "user     77701  0.0  0.0  0  0 ?  S  00:00  0:00 croncopilot start\n"
            "user     77702  0.0  0.0  0  0 ?  S  00:00  0:00 croncopilot start --daemon\n"
            "user     77703  0.0  0.0  0  0 ?  S  00:00  0:00 croncopilot start --foreground\n"
        )
        with patch("subprocess.check_output", return_value=ps_output):
            pids = dm._find_other_croncopilot_pids()
        assert sorted(pids) == [77701, 77702, 77703]

    def test_matches_module_start_variants(self, tmp_dir):
        """python -m croncopilot start 的各种变体都能被识别."""
        dm = DaemonManager(os.path.join(tmp_dir, "test.pid"))
        ps_output = (
            "USER       PID  ..\n"
            "user     88801  0.0  0.0  0  0 ?  S  00:00  0:00 python -m croncopilot start\n"
            "user     88802  0.0  0.0  0  0 ?  S  00:00  0:00 python3 -m croncopilot start --foreground\n"
            "user     88803  0.0  0.0  0  0 ?  S  00:00  0:00 python3.10 -m croncopilot start --daemon\n"
        )
        with patch("subprocess.check_output", return_value=ps_output):
            pids = dm._find_other_croncopilot_pids()
        assert sorted(pids) == [88801, 88802, 88803]


class TestStopExistingInstances:
    """测试 stop_existing_instances 方法."""

    def test_no_existing_instance(self, tmp_dir):
        """无已有实例时正常通过."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)
        with patch.object(dm, "_find_other_croncopilot_pids", return_value=[]):
            dm.stop_existing_instances()  # should not raise

    def test_pid_file_exists_process_alive(self, tmp_dir):
        """PID 文件存在且进程存活时先停止再清理."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("12345")
        dm = DaemonManager(pid_file)

        with patch("os.kill") as mock_kill, \
             patch.object(dm, "_kill_pid", return_value=True) as mock_kp, \
             patch.object(dm, "_find_other_croncopilot_pids", return_value=[]):
            dm.stop_existing_instances()
            # os.kill(pid, 0) is called to check liveness
            mock_kill.assert_called_once_with(12345, 0)
            mock_kp.assert_called_once_with(12345)

        # PID file should be removed
        assert not os.path.isfile(pid_file)

    def test_pid_file_exists_process_dead(self, tmp_dir):
        """PID 文件存在但进程已死时清理 PID 文件."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("12345")
        dm = DaemonManager(pid_file)

        with patch("os.kill", side_effect=ProcessLookupError), \
             patch.object(dm, "_kill_pid") as mock_kp, \
             patch.object(dm, "_find_other_croncopilot_pids", return_value=[]):
            dm.stop_existing_instances()
            mock_kp.assert_not_called()

        assert not os.path.isfile(pid_file)

    def test_orphan_process_found_and_killed(self, tmp_dir):
        """通过 ps 发现残留进程并停止."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        dm = DaemonManager(pid_file)

        with patch.object(dm, "_find_other_croncopilot_pids", return_value=[77777]), \
             patch("os.kill") as mock_kill, \
             patch.object(dm, "_kill_pid", return_value=True) as mock_kp:
            dm.stop_existing_instances()
            # os.kill(77777, 0) for liveness check
            mock_kill.assert_called_once_with(77777, 0)
            mock_kp.assert_called_once_with(77777)

    def test_skips_current_pid(self, tmp_dir):
        """PID 文件指向当前进程时不自杀."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        my_pid = os.getpid()
        with open(pid_file, "w") as f:
            f.write(str(my_pid))
        dm = DaemonManager(pid_file)

        with patch.object(dm, "_kill_pid") as mock_kp, \
             patch.object(dm, "_find_other_croncopilot_pids", return_value=[]):
            dm.stop_existing_instances()
            mock_kp.assert_not_called()

    def test_pid_file_and_orphan(self, tmp_dir):
        """PID 文件和 ps 同时发现不同进程，全部停止."""
        pid_file = os.path.join(tmp_dir, "test.pid")
        with open(pid_file, "w") as f:
            f.write("11111")
        dm = DaemonManager(pid_file)

        kill_targets = []

        def fake_os_kill(pid, sig):
            if sig == 0:
                return  # alive

        with patch("os.kill", side_effect=fake_os_kill), \
             patch.object(dm, "_kill_pid", return_value=True) as mock_kp, \
             patch.object(dm, "_find_other_croncopilot_pids", return_value=[22222]):
            dm.stop_existing_instances()
            # Should have killed both 11111 and 22222
            killed_pids = [c[0][0] for c in mock_kp.call_args_list]
            assert 11111 in killed_pids
            assert 22222 in killed_pids
