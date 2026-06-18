"""Daemon process manager for CronCopilot.

Provides ``DaemonManager`` which handles PID file management, Unix
double-fork daemonisation, process lifecycle, and signal handler
registration.
"""

from __future__ import annotations

import atexit
import os
import re
import signal
import subprocess
import sys
import time
from typing import Callable, List, Optional

from croncopilot.logging.logger import get_logger

logger = get_logger(__name__)


class DaemonManager:
    """Manage CronCopilot as a daemon process.

    Parameters:
        pid_file: Path to the PID file used to track the daemon process.
            The ``~`` prefix is expanded automatically.
    """

    def __init__(self, pid_file: str) -> None:
        self._pid_file: str = os.path.expanduser(pid_file)

    # ------------------------------------------------------------------
    # Daemonisation
    # ------------------------------------------------------------------

    def daemonize(self) -> None:
        """Convert the current process into a Unix daemon (double-fork).

        Performs the classic double-fork sequence:

        1. First ``fork()`` — parent exits.
        2. ``os.setsid()`` — become session leader.
        3. Second ``fork()`` — parent exits.
        4. Redirect *stdin*, *stdout*, *stderr* to ``/dev/null``.
        5. Write the PID file and register cleanup via :func:`atexit`.
        """
        # First fork
        try:
            pid = os.fork()
            if pid > 0:
                # Parent exits
                sys.exit(0)
        except OSError as exc:
            logger.error("First fork failed: %s", exc)
            sys.exit(1)

        # Become session leader
        os.setsid()
        os.umask(0)

        # Second fork
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError as exc:
            logger.error("Second fork failed: %s", exc)
            sys.exit(1)

        # Redirect standard file descriptors to /dev/null
        sys.stdout.flush()
        sys.stderr.flush()

        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, sys.stdin.fileno())
        os.dup2(devnull, sys.stdout.fileno())
        os.dup2(devnull, sys.stderr.fileno())
        os.close(devnull)

        # Write PID file
        self.write_pid()
        atexit.register(self.remove_pid)

        logger.info("Daemonised successfully (PID: %d)", os.getpid())

    # ------------------------------------------------------------------
    # PID file management
    # ------------------------------------------------------------------

    def get_pid(self) -> Optional[int]:
        """Read the PID from the PID file.

        Returns:
            The PID as an integer, or ``None`` if the file does not exist
            or cannot be parsed.
        """
        try:
            if not os.path.isfile(self._pid_file):
                return None
            with open(self._pid_file, "r", encoding="utf-8") as fh:
                pid_str = fh.read().strip()
            return int(pid_str) if pid_str else None
        except (OSError, ValueError) as exc:
            logger.debug("Cannot read PID file %s: %s", self._pid_file, exc)
            return None

    def is_running(self) -> bool:
        """Check whether the daemon process is currently running.

        Reads the PID file and sends signal 0 to verify the process
        exists.

        Returns:
            ``True`` if the process is alive, ``False`` otherwise.
        """
        pid = self.get_pid()
        if pid is None:
            return False

        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we don't have permission to signal it.
            return True
        except OSError:
            return False

    def write_pid(self) -> None:
        """Write the current process PID to the PID file.

        Parent directories are created automatically if necessary.
        """
        pid_dir = os.path.dirname(self._pid_file)
        if pid_dir:
            created = not os.path.isdir(pid_dir)
            os.makedirs(pid_dir, exist_ok=True)
            if created:
                os.chmod(pid_dir, 0o700)
                logger.debug("PID directory created with mode 0700: %s", pid_dir)

        with open(self._pid_file, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
        os.chmod(self._pid_file, 0o600)

        logger.debug("PID file written (mode 0600): %s (PID: %d)", self._pid_file, os.getpid())

    def remove_pid(self) -> None:
        """Delete the PID file if it exists."""
        try:
            if os.path.isfile(self._pid_file):
                os.remove(self._pid_file)
                logger.debug("PID file removed: %s", self._pid_file)
        except OSError as exc:
            logger.warning("Failed to remove PID file %s: %s", self._pid_file, exc)

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    def stop(self) -> bool:
        """Stop the daemon process.

        Sends ``SIGTERM`` and waits up to 10 seconds for the process to
        exit.  If it is still alive after that, ``SIGKILL`` is sent.
        The PID file is cleaned up afterwards.

        Returns:
            ``True`` if the daemon was stopped successfully, ``False``
            otherwise.
        """
        pid = self.get_pid()
        if pid is None:
            logger.warning("No PID file found; daemon may not be running")
            return False

        # Send SIGTERM
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to PID %d", pid)
        except ProcessLookupError:
            logger.info("Process %d already terminated", pid)
            self.remove_pid()
            return True
        except OSError as exc:
            logger.error("Failed to send SIGTERM to PID %d: %s", pid, exc)
            return False

        # Wait for exit (up to 10 seconds)
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                logger.info("Process %d terminated gracefully", pid)
                self.remove_pid()
                return True
            except OSError:
                self.remove_pid()
                return True
            time.sleep(0.1)

        # Still running — escalate to SIGKILL
        logger.warning("Process %d did not terminate; sending SIGKILL", pid)
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except ProcessLookupError:
            pass
        except OSError as exc:
            logger.error("Failed to send SIGKILL to PID %d: %s", pid, exc)
            return False

        self.remove_pid()
        return True

    # ------------------------------------------------------------------
    # Reload notification
    # ------------------------------------------------------------------

    def notify_reload(self) -> bool:
        """通知运行中的 daemon 重新加载任务配置（发送 ``SIGHUP``）。

        读取 PID 文件并向对应进程发送 ``SIGHUP`` 信号。daemon 收到
        ``SIGHUP`` 后会调用 ``scheduler.reload_tasks()`` 从数据库重新
        加载全部任务，从而保证 CLI 对任务的增删改能即时生效，避免
        出现“数据库已改但内存调度器仍用旧配置”的不一致问题。

        Returns:
            ``True`` 表示信号已成功发送；``False`` 表示没有运行中的
            daemon、当前平台不支持 ``SIGHUP`` 或发送失败。
        """
        if not hasattr(signal, "SIGHUP"):
            logger.debug("SIGHUP not available on this platform; skip reload notify")
            return False

        pid = self.get_pid()
        if pid is None:
            logger.debug("No PID file found; daemon may not be running")
            return False

        if not self.is_running():
            logger.debug("Daemon (PID %d) is not running; skip reload notify", pid)
            return False

        try:
            os.kill(pid, signal.SIGHUP)
            logger.info("Sent SIGHUP to daemon (PID: %d) to reload tasks", pid)
            return True
        except ProcessLookupError:
            logger.warning("Daemon PID %d disappeared before SIGHUP was sent", pid)
            return False
        except OSError as exc:
            logger.warning("Failed to send SIGHUP to PID %d: %s", pid, exc)
            return False

    # ------------------------------------------------------------------
    # Single-instance protection
    # ------------------------------------------------------------------

    def _find_other_croncopilot_pids(self) -> List[int]:
        """Find other CronCopilot processes via ``ps``.

        Returns a list of PIDs that belong to CronCopilot processes
        **excluding** the current process.
        """
        my_pid = os.getpid()
        pids: List[int] = []
        try:
            output = subprocess.check_output(
                ["ps", "aux"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for line in output.splitlines():
                # Match lines containing 'croncopilot' but exclude grep itself
                if "croncopilot" not in line:
                    continue
                if "grep" in line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[1])
                except ValueError:
                    continue
                if pid == my_pid:
                    continue
                # Verify this looks like a croncopilot main process
                # (only match real start commands, not editors/debuggers/etc.)
                cmd_part = " ".join(parts[10:]) if len(parts) > 10 else ""
                # 仅匹配 CronCopilot 主进程的启动命令
                is_cli = "croncopilot start" in cmd_part
                is_module = re.search(r"python\S*\s+.*-m\s+croncopilot\s+start", cmd_part) is not None

                if not (is_cli or is_module):
                    continue
                pids.append(pid)
        except (subprocess.SubprocessError, OSError) as exc:
            logger.debug("Failed to enumerate processes via ps: %s", exc)
        return pids

    def _kill_pid(self, pid: int, timeout: float = 5.0) -> bool:
        """Send SIGTERM to *pid*, wait, then escalate to SIGKILL.

        Returns ``True`` if the process was terminated.
        """
        # SIGTERM
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to PID %d", pid)
        except ProcessLookupError:
            logger.debug("PID %d already gone", pid)
            return True
        except OSError as exc:
            logger.warning("Cannot send SIGTERM to PID %d: %s", pid, exc)
            return False

        # Wait
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                logger.info("PID %d terminated gracefully", pid)
                return True
            except OSError:
                return True
            time.sleep(0.1)

        # Escalate
        logger.warning("PID %d did not stop in %.1fs; sending SIGKILL", pid, timeout)
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except ProcessLookupError:
            pass
        except OSError as exc:
            logger.error("Failed to SIGKILL PID %d: %s", pid, exc)
            return False
        return True

    def stop_existing_instances(self) -> None:
        """Ensure no other CronCopilot instance is running.

        1. Check the PID file; if the recorded process is alive, stop it.
        2. Scan for any remaining CronCopilot processes (e.g. started
           via *launchd*) and stop them as well.
        3. Clean up the stale PID file.
        """
        # --- Phase 1: PID file ---
        pid = self.get_pid()
        if pid is not None:
            if pid == os.getpid():
                # Should not happen, but guard against killing ourselves.
                pass
            else:
                try:
                    os.kill(pid, 0)
                    # Process is alive
                    logger.info(
                        "检测到已有实例运行 (PID: %d)，正在停止...", pid
                    )
                    self._kill_pid(pid)
                except ProcessLookupError:
                    logger.info(
                        "PID 文件指向已终止的进程 %d，清理残留 PID 文件", pid
                    )
                except PermissionError:
                    logger.info(
                        "检测到已有实例运行 (PID: %d, 权限受限)，尝试停止...", pid
                    )
                    self._kill_pid(pid)
                except OSError:
                    pass
            self.remove_pid()

        # --- Phase 2: scan for orphan processes ---
        other_pids = self._find_other_croncopilot_pids()
        for other_pid in other_pids:
            try:
                os.kill(other_pid, 0)
            except (ProcessLookupError, OSError):
                continue
            logger.info(
                "发现残留 CronCopilot 进程 (PID: %d)，正在停止...", other_pid
            )
            self._kill_pid(other_pid)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def setup_signal_handlers(
        self,
        shutdown_callback: Callable[[], None],
        reload_callback: Callable[[], None],
    ) -> None:
        """Register signal handlers for graceful shutdown and config reload.

        Parameters:
            shutdown_callback: Invoked on ``SIGTERM`` and ``SIGINT`` for
                graceful shutdown.
            reload_callback: Invoked on ``SIGHUP`` to trigger
                configuration reload.
        """

        def _handle_shutdown(signum: int, frame: object) -> None:
            logger.info("Received signal %d — initiating shutdown", signum)
            shutdown_callback()

        def _handle_reload(signum: int, frame: object) -> None:
            logger.info("Received SIGHUP — reloading configuration")
            reload_callback()

        signal.signal(signal.SIGTERM, _handle_shutdown)
        signal.signal(signal.SIGINT, _handle_shutdown)

        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _handle_reload)

        logger.info("Signal handlers registered (SIGTERM, SIGINT, SIGHUP)")
