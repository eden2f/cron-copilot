"""Daemon process manager for PyCronGuard.

Provides ``DaemonManager`` which handles PID file management, Unix
double-fork daemonisation, process lifecycle, and signal handler
registration.
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
import time
from typing import Callable, Optional

from pycronguard.logging.logger import get_logger

logger = get_logger(__name__)


class DaemonManager:
    """Manage PyCronGuard as a daemon process.

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
            os.makedirs(pid_dir, exist_ok=True)

        with open(self._pid_file, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))

        logger.debug("PID file written: %s (PID: %d)", self._pid_file, os.getpid())

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
