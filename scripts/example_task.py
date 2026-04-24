#!/usr/bin/env python3
"""PyCronGuard 示例任务脚本。

本脚本演示如何编写一个与 PyCronGuard 兼容的定时任务脚本。

兼容性要求:
    - 脚本通过 ``python script.py`` 方式调用。
    - 退出码 0 表示成功，非 0 表示失败。
    - 标准输出 (stdout) 会被 PyCronGuard 捕获并记录。
    - 标准错误 (stderr) 会被 PyCronGuard 捕获并在失败时用于告警。

使用方法:
    # 注册脚本
    pycronguard script add --path scripts/example_task.py --name example

    # 创建定时任务（每 5 分钟执行一次）
    pycronguard task add --name example-task \\
        --script scripts/example_task.py \\
        --schedule-type interval --schedule 5m

    # 手动执行一次
    pycronguard task run example-task
"""

from __future__ import annotations

import sys
import time
from datetime import datetime


def main() -> int:
    """任务主函数。

    Returns:
        退出码: 0 表示成功，1 表示失败。
    """
    start_time = time.monotonic()

    print(f"[{datetime.now().isoformat()}] 示例任务开始执行")
    print(f"  Python 版本: {sys.version}")
    print(f"  工作目录:    {__file__}")

    try:
        # ---- 在这里编写你的任务逻辑 ----
        # 示例: 模拟一些工作
        print("  正在处理数据 ...")
        time.sleep(2)
        print("  数据处理完成")

        # 输出执行结果
        elapsed = time.monotonic() - start_time
        print(f"[{datetime.now().isoformat()}] 任务执行成功 (耗时: {elapsed:.2f}s)")

        return 0  # 成功

    except Exception as exc:
        # 错误信息写入 stderr，PyCronGuard 会捕获并用于告警
        elapsed = time.monotonic() - start_time
        print(f"[{datetime.now().isoformat()}] 任务执行失败 (耗时: {elapsed:.2f}s)", file=sys.stderr)
        print(f"  错误: {exc}", file=sys.stderr)

        return 1  # 失败


if __name__ == "__main__":
    sys.exit(main())
