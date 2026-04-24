"""System service configuration generator for PyCronGuard.

Generates platform-specific service definition files (systemd, launchd,
Windows batch) and provides installation guidance.
"""

from __future__ import annotations

import getpass
import os
import platform
import sys
import textwrap
from pathlib import Path
from typing import Optional

from pycronguard.logging.logger import get_logger

logger = get_logger(__name__)


class ServiceGenerator:
    """Generate platform-specific service configuration files.

    Parameters:
        python_path: Absolute path to the Python interpreter.  Defaults
            to ``sys.executable``.
        install_path: Base installation directory.  Defaults to
            ``~/.pycronguard``.
    """

    def __init__(
        self,
        python_path: Optional[str] = None,
        install_path: Optional[str] = None,
    ) -> None:
        self._python_path: str = python_path or sys.executable
        self._install_path: str = install_path or os.path.expanduser("~/.pycronguard")

    # ------------------------------------------------------------------
    # Platform detection
    # ------------------------------------------------------------------

    def detect_platform(self) -> str:
        """Detect the current operating-system platform.

        Returns:
            One of ``'linux'``, ``'macos'``, or ``'windows'``.
        """
        system = platform.system().lower()
        if system == "darwin":
            return "macos"
        elif system == "windows":
            return "windows"
        else:
            return "linux"

    # ------------------------------------------------------------------
    # Generation dispatch
    # ------------------------------------------------------------------

    def generate(self, output_dir: Optional[str] = None) -> str:
        """Generate a service configuration file for the current platform.

        Parameters:
            output_dir: Directory to write the generated file into.
                Defaults to ``<install_path>/deploy``.

        Returns:
            Absolute path to the generated configuration file.
        """
        output_dir = output_dir or os.path.join(self._install_path, "deploy")
        os.makedirs(output_dir, exist_ok=True)

        plat = self.detect_platform()

        if plat == "linux":
            output_path = os.path.join(output_dir, "pycronguard.service")
            return self.generate_systemd(output_path)
        elif plat == "macos":
            output_path = os.path.join(output_dir, "com.pycronguard.plist")
            return self.generate_launchd(output_path)
        else:
            output_path = os.path.join(output_dir, "pycronguard.bat")
            return self.generate_windows(output_path)

    # ------------------------------------------------------------------
    # systemd
    # ------------------------------------------------------------------

    def generate_systemd(self, output_path: str) -> str:
        """Generate a systemd unit file.

        Parameters:
            output_path: Destination file path.

        Returns:
            Absolute path to the written file.
        """
        user = getpass.getuser()
        home = os.path.expanduser("~")

        content = textwrap.dedent(f"""\
            [Unit]
            Description=PyCronGuard - Python Task Scheduler
            After=network.target

            [Service]
            Type=simple
            User={user}
            ExecStart={self._python_path} -m pycronguard start --foreground
            WorkingDirectory={home}
            Restart=on-failure
            RestartSec=5
            StandardOutput=journal
            StandardError=journal
            Environment=PATH={os.path.dirname(self._python_path)}:/usr/bin:/bin

            [Install]
            WantedBy=multi-user.target
        """)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        logger.info("Generated systemd unit file: %s", output_path)
        return os.path.abspath(output_path)

    # ------------------------------------------------------------------
    # launchd
    # ------------------------------------------------------------------

    def generate_launchd(self, output_path: str) -> str:
        """Generate a macOS launchd plist file.

        Parameters:
            output_path: Destination file path.

        Returns:
            Absolute path to the written file.
        """
        log_dir = os.path.join(self._install_path, "logs")

        content = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>com.pycronguard</string>

                <key>ProgramArguments</key>
                <array>
                    <string>{self._python_path}</string>
                    <string>-m</string>
                    <string>pycronguard</string>
                    <string>start</string>
                    <string>--foreground</string>
                </array>

                <key>RunAtLoad</key>
                <true/>

                <key>KeepAlive</key>
                <true/>

                <key>StandardOutPath</key>
                <string>{log_dir}/launchd_stdout.log</string>

                <key>StandardErrorPath</key>
                <string>{log_dir}/launchd_stderr.log</string>

                <key>WorkingDirectory</key>
                <string>{os.path.expanduser("~")}</string>
            </dict>
            </plist>
        """)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        logger.info("Generated launchd plist file: %s", output_path)
        return os.path.abspath(output_path)

    # ------------------------------------------------------------------
    # Windows
    # ------------------------------------------------------------------

    def generate_windows(self, output_path: str) -> str:
        """Generate a Windows startup batch script.

        Parameters:
            output_path: Destination file path.

        Returns:
            Absolute path to the written file.
        """
        content = textwrap.dedent(f"""\
            @echo off
            REM PyCronGuard - Windows Startup Script
            REM Place this file in shell:startup to run at login

            title PyCronGuard
            echo Starting PyCronGuard ...
            "{self._python_path}" -m pycronguard start --foreground
            pause
        """)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        logger.info("Generated Windows startup script: %s", output_path)
        return os.path.abspath(output_path)

    # ------------------------------------------------------------------
    # Installation guidance
    # ------------------------------------------------------------------

    def install_service(self) -> bool:
        """Print platform-specific installation instructions.

        Does *not* execute privileged commands; instead prints the
        commands the user should run manually.

        Returns:
            ``True`` after printing instructions.
        """
        plat = self.detect_platform()
        output_path = self.generate()

        print("\n" + "=" * 60)
        print("PyCronGuard 服务安装指南")
        print("=" * 60)

        if plat == "linux":
            print(f"\n已生成 systemd 服务文件: {output_path}")
            print("\n请执行以下命令安装服务:")
            print(f"  sudo cp {output_path} /etc/systemd/system/pycronguard.service")
            print("  sudo systemctl daemon-reload")
            print("  sudo systemctl enable pycronguard")
            print("  sudo systemctl start pycronguard")
            print("\n查看状态:")
            print("  sudo systemctl status pycronguard")
            print("  journalctl -u pycronguard -f")

        elif plat == "macos":
            plist_dest = os.path.expanduser("~/Library/LaunchAgents/com.pycronguard.plist")
            print(f"\n已生成 launchd 配置: {output_path}")
            print("\n请执行以下命令安装服务:")
            print(f"  cp {output_path} {plist_dest}")
            print(f"  launchctl load {plist_dest}")
            print("\n停止服务:")
            print(f"  launchctl unload {plist_dest}")

        elif plat == "windows":
            print(f"\n已生成启动脚本: {output_path}")
            print("\n安装方式 (任选其一):")
            print("  1. 将 bat 文件复制到启动文件夹:")
            print("     Win+R → 输入 shell:startup → 回车 → 粘贴文件")
            print("  2. 使用任务计划程序创建开机启动任务")

        print("\n" + "=" * 60)
        return True
