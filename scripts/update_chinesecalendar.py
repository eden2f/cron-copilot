#!/usr/bin/env python3
"""chinesecalendar 依赖年度更新脚本。

本脚本用于每年自动更新 chinesecalendar 库，以获取最新的中国法定节假日数据。
chinesecalendar 的节假日数据是静态打包在库中的，需要每年更新一次。

兼容性要求:
    - 脚本通过 ``python script.py`` 方式调用。
    - 退出码 0 表示成功，非 0 表示失败。
    - 标准输出 (stdout) 会被 PyCronGuard 捕获并记录。
    - 标准错误 (stderr) 会被 PyCronGuard 捕获并在失败时用于告警。

使用方法:
    # 注册脚本
    pycronguard script add --path scripts/update_chinesecalendar.py --name update-calendar

    # 创建定时任务（每年 1 月 5 日凌晨 3 点执行，等待官方发布新年数据）
    pycronguard task add --name update-chinesecalendar \
        --script scripts/update_chinesecalendar.py \
        --schedule-type cron --schedule "0 3 5 1 *"
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime


def _get_installed_version() -> str | None:
    """获取当前已安装的 chinesecalendar 版本号。

    Returns:
        版本号字符串，未安装时返回 None。
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "chinesecalendar"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            match = re.search(r"^Version:\s*(.+)$", result.stdout, re.MULTILINE)
            if match:
                return match.group(1).strip()
    except Exception:
        pass
    return None


def main() -> int:
    """执行 chinesecalendar 更新。

    Returns:
        退出码: 0 表示成功，1 表示失败。
    """
    start_time = time.monotonic()

    print(f"[{datetime.now().isoformat()}] chinesecalendar 更新任务开始执行")
    print(f"  Python 解释器: {sys.executable}")
    print(f"  Python 版本:   {sys.version}")

    try:
        # 记录更新前的版本
        old_version = _get_installed_version()
        print(f"  当前版本: {old_version or '未安装'}")

        # 执行 pip 升级
        print("  正在执行 pip install -U chinesecalendar ...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "chinesecalendar"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # 输出 pip 日志（用于排查问题）
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                print(f"  [pip] {line}")
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                print(f"  [pip-stderr] {line}")

        if result.returncode != 0:
            elapsed = time.monotonic() - start_time
            print(
                f"[{datetime.now().isoformat()}] 更新失败: pip 返回码 {result.returncode} (耗时: {elapsed:.2f}s)",
                file=sys.stderr,
            )
            return 1

        # 记录更新后的版本
        new_version = _get_installed_version()
        print(f"  更新后版本: {new_version or '未知'}")

        # 汇总结果
        elapsed = time.monotonic() - start_time
        if old_version and new_version and old_version != new_version:
            print(f"[{datetime.now().isoformat()}] 更新成功: {old_version} -> {new_version} (耗时: {elapsed:.2f}s)")
        elif old_version == new_version:
            print(f"[{datetime.now().isoformat()}] 已是最新版本: {new_version} (耗时: {elapsed:.2f}s)")
        else:
            print(f"[{datetime.now().isoformat()}] 安装成功: {new_version} (耗时: {elapsed:.2f}s)")

        return 0  # 成功

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start_time
        print(f"[{datetime.now().isoformat()}] 更新失败: pip 执行超时 (耗时: {elapsed:.2f}s)", file=sys.stderr)
        return 1

    except Exception as exc:
        # 错误信息写入 stderr，PyCronGuard 会捕获并用于告警
        elapsed = time.monotonic() - start_time
        print(f"[{datetime.now().isoformat()}] 更新失败 (耗时: {elapsed:.2f}s)", file=sys.stderr)
        print(f"  错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
