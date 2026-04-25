"""服务配置生成器测试 — ServiceGenerator."""

import os
import sys
from unittest.mock import patch

import pytest

from croncopilot.deploy.service import ServiceGenerator


class TestServiceGeneratorInit:
    """测试 ServiceGenerator 初始化."""

    def test_default_paths(self):
        """默认路径使用 sys.executable 和 ~/.croncopilot."""
        gen = ServiceGenerator()
        assert gen._python_path == sys.executable
        assert gen._install_path == os.path.expanduser("~/.croncopilot")

    def test_custom_paths(self):
        """自定义路径正确赋值."""
        gen = ServiceGenerator(
            python_path="/usr/bin/python3",
            install_path="/opt/croncopilot",
        )
        assert gen._python_path == "/usr/bin/python3"
        assert gen._install_path == "/opt/croncopilot"

    def test_partial_custom_python_path(self):
        """仅自定义 python_path，install_path 使用默认值."""
        gen = ServiceGenerator(python_path="/custom/python")
        assert gen._python_path == "/custom/python"
        assert gen._install_path == os.path.expanduser("~/.croncopilot")

    def test_partial_custom_install_path(self):
        """仅自定义 install_path，python_path 使用默认值."""
        gen = ServiceGenerator(install_path="/custom/install")
        assert gen._python_path == sys.executable
        assert gen._install_path == "/custom/install"


class TestDetectPlatform:
    """测试平台检测."""

    @patch("croncopilot.deploy.service.platform.system", return_value="Linux")
    def test_linux(self, mock_sys):
        gen = ServiceGenerator()
        assert gen.detect_platform() == "linux"

    @patch("croncopilot.deploy.service.platform.system", return_value="Darwin")
    def test_macos(self, mock_sys):
        gen = ServiceGenerator()
        assert gen.detect_platform() == "macos"

    @patch("croncopilot.deploy.service.platform.system", return_value="Windows")
    def test_windows(self, mock_sys):
        gen = ServiceGenerator()
        assert gen.detect_platform() == "windows"

    @patch("croncopilot.deploy.service.platform.system", return_value="FreeBSD")
    def test_unknown_defaults_to_linux(self, mock_sys):
        """未知平台回退为 linux."""
        gen = ServiceGenerator()
        assert gen.detect_platform() == "linux"


class TestGenerate:
    """测试 generate 根据平台调度到正确的方法."""

    @patch("croncopilot.deploy.service.platform.system", return_value="Linux")
    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_generate_linux(self, mock_user, mock_sys, tmp_dir):
        """Linux 平台生成 systemd 文件."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        result = gen.generate(output_dir=tmp_dir)
        assert result.endswith("croncopilot.service")
        assert os.path.isfile(result)

    @patch("croncopilot.deploy.service.platform.system", return_value="Darwin")
    def test_generate_macos(self, mock_sys, tmp_dir):
        """macOS 平台生成 launchd plist 文件."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        result = gen.generate(output_dir=tmp_dir)
        assert result.endswith("com.croncopilot.plist")
        assert os.path.isfile(result)

    @patch("croncopilot.deploy.service.platform.system", return_value="Windows")
    def test_generate_windows(self, mock_sys, tmp_dir):
        """Windows 平台生成 bat 脚本."""
        gen = ServiceGenerator(python_path="C:\\Python\\python.exe", install_path=tmp_dir)
        result = gen.generate(output_dir=tmp_dir)
        assert result.endswith("croncopilot.bat")
        assert os.path.isfile(result)

    @patch("croncopilot.deploy.service.platform.system", return_value="Linux")
    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_generate_default_output_dir(self, mock_user, mock_sys, tmp_dir):
        """未指定 output_dir 时使用 install_path/deploy."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        result = gen.generate()
        expected_dir = os.path.join(tmp_dir, "deploy")
        assert os.path.dirname(result) == os.path.abspath(expected_dir)


class TestGenerateSystemd:
    """测试 systemd unit 文件生成."""

    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_file_created(self, mock_user, tmp_dir):
        """文件被正确创建."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "croncopilot.service")
        result = gen.generate_systemd(output_path)
        assert os.path.isfile(result)

    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_content_fields(self, mock_user, tmp_dir):
        """关键字段存在于生成的内容中."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "croncopilot.service")
        gen.generate_systemd(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "[Unit]" in content
        assert "Description=CronCopilot" in content
        assert "[Service]" in content
        assert "User=testuser" in content
        assert "ExecStart=/usr/bin/python3 -m croncopilot start --foreground" in content
        assert "Restart=on-failure" in content
        assert "RestartSec=5" in content
        assert "[Install]" in content
        assert "WantedBy=multi-user.target" in content

    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_returns_absolute_path(self, mock_user, tmp_dir):
        """返回绝对路径."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "croncopilot.service")
        result = gen.generate_systemd(output_path)
        assert os.path.isabs(result)

    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_nested_output_dir(self, mock_user, tmp_dir):
        """嵌套目录自动创建."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "a", "b", "croncopilot.service")
        result = gen.generate_systemd(output_path)
        assert os.path.isfile(result)


class TestGenerateLaunchd:
    """测试 launchd plist 文件生成."""

    def test_file_created(self, tmp_dir):
        """文件被正确创建."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "com.croncopilot.plist")
        result = gen.generate_launchd(output_path)
        assert os.path.isfile(result)

    def test_xml_format(self, tmp_dir):
        """内容为有效的 XML plist 格式."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "com.croncopilot.plist")
        gen.generate_launchd(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert '<?xml version="1.0"' in content
        assert "<plist" in content
        assert "</plist>" in content

    def test_content_fields(self, tmp_dir):
        """关键字段存在于生成的 plist 中."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "com.croncopilot.plist")
        gen.generate_launchd(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "<key>Label</key>" in content
        assert "<string>com.croncopilot</string>" in content
        assert "<key>ProgramArguments</key>" in content
        assert "<string>/usr/bin/python3</string>" in content
        assert "<key>KeepAlive</key>" in content
        assert "<true/>" in content
        assert "<key>RunAtLoad</key>" in content
        assert "<key>WorkingDirectory</key>" in content

    def test_log_paths_use_install_path(self, tmp_dir):
        """日志路径基于 install_path."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path="/opt/cc")
        output_path = os.path.join(tmp_dir, "com.croncopilot.plist")
        gen.generate_launchd(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "/opt/cc/logs/launchd_stdout.log" in content
        assert "/opt/cc/logs/launchd_stderr.log" in content

    def test_returns_absolute_path(self, tmp_dir):
        """返回绝对路径."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "com.croncopilot.plist")
        result = gen.generate_launchd(output_path)
        assert os.path.isabs(result)


class TestGenerateWindows:
    """测试 Windows bat 脚本生成."""

    def test_file_created(self, tmp_dir):
        """文件被正确创建."""
        gen = ServiceGenerator(python_path="C:\\Python\\python.exe", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "croncopilot.bat")
        result = gen.generate_windows(output_path)
        assert os.path.isfile(result)

    def test_content_fields(self, tmp_dir):
        """bat 脚本包含关键内容."""
        gen = ServiceGenerator(python_path="C:\\Python\\python.exe", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "croncopilot.bat")
        gen.generate_windows(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "@echo off" in content
        assert "CronCopilot" in content
        assert "C:\\Python\\python.exe" in content
        assert "-m croncopilot start --foreground" in content
        assert "pause" in content

    def test_returns_absolute_path(self, tmp_dir):
        """返回绝对路径."""
        gen = ServiceGenerator(python_path="C:\\Python\\python.exe", install_path=tmp_dir)
        output_path = os.path.join(tmp_dir, "croncopilot.bat")
        result = gen.generate_windows(output_path)
        assert os.path.isabs(result)


class TestInstallService:
    """测试安装指导输出."""

    @patch("croncopilot.deploy.service.platform.system", return_value="Linux")
    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_linux_instructions(self, mock_user, mock_sys, tmp_dir, capsys):
        """Linux 平台打印 systemd 安装指导."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        result = gen.install_service()
        assert result is True

        captured = capsys.readouterr()
        assert "CronCopilot 服务安装指南" in captured.out
        assert "systemd" in captured.out
        assert "systemctl" in captured.out
        assert "daemon-reload" in captured.out

    @patch("croncopilot.deploy.service.platform.system", return_value="Darwin")
    def test_macos_instructions(self, mock_sys, tmp_dir, capsys):
        """macOS 平台打印 launchd 安装指导."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        result = gen.install_service()
        assert result is True

        captured = capsys.readouterr()
        assert "CronCopilot 服务安装指南" in captured.out
        assert "launchd" in captured.out
        assert "launchctl" in captured.out

    @patch("croncopilot.deploy.service.platform.system", return_value="Windows")
    def test_windows_instructions(self, mock_sys, tmp_dir, capsys):
        """Windows 平台打印启动脚本指导."""
        gen = ServiceGenerator(python_path="C:\\Python\\python.exe", install_path=tmp_dir)
        result = gen.install_service()
        assert result is True

        captured = capsys.readouterr()
        assert "CronCopilot 服务安装指南" in captured.out
        assert "shell:startup" in captured.out
        assert "任务计划程序" in captured.out

    @patch("croncopilot.deploy.service.platform.system", return_value="Linux")
    @patch("croncopilot.deploy.service.getpass.getuser", return_value="testuser")
    def test_install_generates_file(self, mock_user, mock_sys, tmp_dir):
        """install_service 会实际生成配置文件."""
        gen = ServiceGenerator(python_path="/usr/bin/python3", install_path=tmp_dir)
        gen.install_service()
        deploy_dir = os.path.join(tmp_dir, "deploy")
        assert os.path.isdir(deploy_dir)
        files = os.listdir(deploy_dir)
        assert len(files) == 1
