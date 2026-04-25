# CronCopilot

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS-lightgrey.svg)]()

**CronCopilot** 是一个功能完备的 Python 定时任务管理与监控系统，提供任务调度、脚本管理、运行监控、告警通知和异常自愈等能力。

## 功能特性

- **灵活调度** — 支持 cron 表达式、每日/每周/每月/间隔等多种调度方式
- **节假日感知** — 支持中国法定节假日/工作日识别，任务可配置仅工作日、仅节假日、跳过节假日等模式
- **优先级队列** — 基于堆的任务优先级排序，支持并发控制和依赖管理
- **任务依赖** — 支持任务间依赖关系，控制执行顺序
- **单任务并发控制** — 每个任务可独立配置最大并发实例数
- **脚本管理** — 脚本注册、版本控制、语法校验、自动备份
- **虚拟环境隔离** — 为脚本指定独立 Python 环境，避免依赖冲突
- **实时监控** — 任务执行追踪、系统资源指标采集 (CPU/内存/磁盘)
- **执行历史与统计** — 完整的任务执行记录和失败率分析
- **智能告警** — 即时失败告警、连续失败告警、性能阈值告警，支持邮件通知
- **异常自愈** — 自动重试 (指数退避)、健康检查、死锁检测与自动终止
- **守护进程** — 支持前台/后台运行，PID 管理，优雅关闭
- **配置热重载** — 修改配置后发送 SIGHUP 信号即可生效，无需重启
- **系统服务** — 自动生成 systemd / launchd / Windows 服务配置

## 系统要求

- **Python：** 3.10 及以上
- **操作系统：** Linux, macOS（Windows 可通过 WSL2 使用）
- **数据库：** SQLite（内置，无需单独安装）

### 核心依赖

| 包名 | 版本要求 | 说明 |
|------|---------|------|
| apscheduler | >=3.10.0 | 任务调度引擎 |
| pyyaml | >=6.0 | 配置文件解析 |
| sqlalchemy | >=2.0 | ORM 数据存储 |
| click | >=8.0 | CLI 框架 |
| psutil | >=5.9 | 系统资源监控 |
| watchdog | >=3.0 | 文件系统变更监听 |
| chinesecalendar | >=1.0 | 中国节假日识别 |

## 快速开始

### 安装

```bash
# 克隆项目
git clone https://gitee.com/eden2f/cron-copilot.git
cd CronCopilot

# 安装（开发模式）
pip install -e .

# 安装开发依赖
pip install -e ".[dev]"
```

### 初始化

```bash
# 创建目录结构和默认配置
croncopilot init
```

这将在 `~/.croncopilot/` 下创建：
- `config.yaml` — 配置文件
- `data.db` — SQLite 数据库
- `logs/` — 日志目录
- `scripts/` — 脚本目录
- `script_versions/` — 脚本版本备份

### 添加任务

```bash
# 注册脚本
croncopilot script add --path scripts/example_task.py --name example

# 添加定时任务（每 5 分钟执行）
croncopilot task add \
    --name my-task \
    --script scripts/example_task.py \
    --schedule-type interval \
    --schedule 5m

# 添加 cron 任务（每天 8:00）
croncopilot task add \
    --name daily-report \
    --script scripts/example_task.py \
    --schedule-type daily \
    --schedule "08:00"

# 添加仅工作日执行的任务（自动识别法定节假日和调休）
croncopilot task add \
    --name workday-report \
    --script scripts/example_task.py \
    --schedule-type daily \
    --schedule "09:00" \
    --holiday-mode workday_only

# 手动执行一次
croncopilot task run my-task
```

### 启动调度器

```bash
# 前台运行
croncopilot start

# 后台守护进程
croncopilot start --daemon

# 查看状态
croncopilot status

# 停止
croncopilot stop
```

## 升级

### 开发模式

本项目采用 `pip install -e .` 开发模式安装，源码修改后自动生效，无需重新安装。
升级代码后，重启服务即可：

```bash
croncopilot stop && croncopilot start --daemon
```

### 生产部署

若通过 `pip install .` 部署，需重新安装后重启：

```bash
pip install --upgrade .
croncopilot stop && croncopilot start --daemon
```

> **提示：** 如果仅修改了配置文件，可通过[配置热重载](#配置热重载)方式生效，无需重启服务。

## CLI 命令参考

### 全局选项

| 选项 | 说明 |
|------|------|
| `-c, --config PATH` | 指定配置文件路径 |
| `-v, --verbose` | 详细输出 |

### 核心命令

| 命令 | 说明 |
|------|------|
| `croncopilot init` | 初始化配置和目录结构 |
| `croncopilot start [-d/--daemon]` | 启动调度器 |
| `croncopilot stop` | 停止守护进程 |
| `croncopilot status` | 查看运行状态 |
| `croncopilot health` | 执行系统健康检查 |

### 任务管理

| 命令 | 说明 |
|------|------|
| `croncopilot task add` | 添加新任务 |
| `croncopilot task remove <name>` | 删除任务 |
| `croncopilot task list` | 列出所有任务 |
| `croncopilot task run <name>` | 立即执行一次任务 |
| `croncopilot task history <name>` | 查看任务执行历史和统计 |

**task add 选项：**

| 选项 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `-n, --name` | 是 | — | 任务名称 |
| `-s, --script` | 是 | — | 脚本路径 |
| `-t, --schedule-type` | 是 | — | 调度类型 (cron/daily/weekly/monthly/interval) |
| `-S, --schedule` | 是 | — | 调度表达式 |
| `-p, --priority` | 否 | `5` | 优先级 1-10 |
| `--timeout` | 否 | `3600` | 超时时间(秒) |
| `--max-retries` | 否 | `3` | 最大重试次数 |
| `--max-instances` | 否 | `1` | 最大并发实例数 |
| `--category` | 否 | `""` | 分类 |
| `--description` | 否 | `""` | 描述 |
| `--depends-on` | 否 | — | 依赖的任务名称（可多次指定） |
| `--holiday-mode` | 否 | `none` | 节假日模式 (none/workday_only/holiday_only/skip_holiday/skip_workday) |

### 脚本管理

| 命令 | 说明 |
|------|------|
| `croncopilot script add` | 注册脚本（支持 `--venv` 指定独立虚拟环境路径） |
| `croncopilot script remove <name>` | 注销脚本 |
| `croncopilot script list` | 列出所有脚本 |
| `croncopilot script info <name>` | 查看脚本详情和版本历史 |

### 任务执行历史

```bash
# 查看最近 30 天的执行记录和统计
croncopilot task history <name>

# 查看最近 7 天，显示 50 条记录（支持短选项）
croncopilot task history <name> -d 7 -l 50

# 仅查看统计摘要
croncopilot task history <name> --stats-only
```

### 调度表达式格式

| 类型 | 格式 | 示例 |
|------|------|------|
| `cron` | 标准 5 段 cron | `0 8 * * *` (每天 8:00) |
| `daily` | `HH:MM` | `08:00` |
| `weekly` | `day@HH:MM` | `mon@08:00` (每周一 8:00) |
| `monthly` | `day@HH:MM` | `1@08:00` (每月 1 日 8:00) |
| `interval` | `<数字><单位>` | `30m`, `2h`, `1d`, `90s` |

## 节假日/工作日识别

CronCopilot 集成了 `chinesecalendar` 库，支持中国法定节假日和调休工作日的智能识别。

### 节假日模式

通过 `--holiday-mode` 参数控制任务的节假日行为：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `none` | 不启用节假日感知（默认） | 普通定时任务 |
| `workday_only` | 仅工作日执行（含调休工作日，排除法定节假日和周末） | 工作日报表、数据同步 |
| `holiday_only` | 仅节假日/周末执行 | 节假日维护任务 |
| `skip_holiday` | 常规调度，遇法定节假日跳过 | 日常任务，节假日暂停 |
| `skip_workday` | 常规调度，遇工作日跳过 | 仅在休息日运行的任务 |

### 使用示例

```bash
# 仅工作日执行（自动识别法定节假日、调休工作日）
croncopilot task add -n daily-report \
    -s scripts/report.py -t daily -S "09:00" \
    --holiday-mode workday_only

# 仅法定节假日执行
croncopilot task add -n holiday-maintenance \
    -s scripts/maintenance.py -t daily -S "02:00" \
    --holiday-mode holiday_only

# 每天执行，但法定节假日跳过
croncopilot task add -n data-sync \
    -s scripts/sync.py -t daily -S "12:00" \
    --holiday-mode skip_holiday
```

### 数据更新

节假日数据来自 `chinesecalendar` 库，基于国务院每年发布的节假日安排。建议每年初更新依赖以获取最新数据：

```bash
pip install -U chinesecalendar
```

**自动更新（推荐）：** 项目内置了更新脚本，可注册为年度定时任务：

```bash
croncopilot script add --path scripts/update_chinesecalendar.py --name update-calendar
croncopilot task add --name update-chinesecalendar \
    --script scripts/update_chinesecalendar.py \
    --schedule-type cron --schedule "0 3 5 1 *"
```

该任务将在每年 1 月 5 日凌晨 3 点自动执行，届时国务院通常已发布当年节假日安排。

## 配置文件说明

配置文件位于 `~/.croncopilot/config.yaml`，支持以下配置项：

```yaml
# 调度器配置
scheduler:
  max_workers: 4          # 线程池最大工作线程数
  max_instances: 1        # 同一任务最大并发实例数
  timezone: "Asia/Shanghai"

# 数据库存储配置
storage:
  db_path: "~/.croncopilot/data.db"

# 日志配置
log:
  log_dir: "~/.croncopilot/logs"
  level: "INFO"           # DEBUG / INFO / WARNING / ERROR / CRITICAL
  max_days: 30
  json_format: true

# 告警配置
alert:
  failure_immediate: true
  consecutive_failure_threshold: 3
  cooldown_seconds: 300
  email:
    enabled: false
    smtp_host: ""
    smtp_port: 587
    use_tls: true
    username: ""
    password: ""
    sender: ""
    recipients: []

# 恢复与健康检查
recovery:
  max_retries: 3
  retry_delay: 10.0
  backoff_factor: 2.0
  health_check_interval: 60
  cpu_threshold: 90.0
  memory_threshold: 90.0
  disk_threshold: 90.0
  task_timeout: 3600

# 脚本管理
script:
  script_dir: "~/.croncopilot/scripts"
  version_dir: "~/.croncopilot/script_versions"
  max_versions: 10

# PID 文件
pid_file: "~/.croncopilot/croncopilot.pid"
```

## 配置热重载

修改 `config.yaml` 后，无需重启服务，发送 `SIGHUP` 信号即可热重载配置：

```bash
kill -HUP $(cat ~/.croncopilot/croncopilot.pid)
```

**热重载作用：**
- 重新加载所有配置项（调度器参数、告警设置、日志级别等）
- 刷新已有任务的调度参数（如 misfire_grace_time、coalesce、max_instances）

**注意：** 任务定义的新增/删除需通过 `croncopilot task add/remove` CLI 命令完成，热重载仅作用于配置项。

## 系统服务部署

### Linux (systemd)

```bash
# 生成服务文件（自动检测平台）
# 或直接使用 deploy/croncopilot.service 模板

sudo cp deploy/croncopilot.service /etc/systemd/system/
# 编辑文件替换 %USER%, %PYTHON%, %HOME% 占位符
sudo systemctl daemon-reload
sudo systemctl enable croncopilot
sudo systemctl start croncopilot
```

### macOS (launchd)

```bash
cp deploy/com.croncopilot.plist ~/Library/LaunchAgents/
# 编辑文件替换 %PYTHON%, %HOME% 占位符
launchctl load ~/Library/LaunchAgents/com.croncopilot.plist
```

### 使用内置生成器

```python
from croncopilot.deploy.service import ServiceGenerator

generator = ServiceGenerator()
generator.install_service()  # 自动检测平台并生成配置
```

## 架构说明

```
CronCopilot
├── config/         配置管理 (YAML 加载、Schema 校验、热加载)
├── core/           核心调度 (APScheduler 集成、任务执行器、优先级队列、节假日识别)
├── storage/        数据持久化 (SQLAlchemy ORM、SQLite)
├── scripts/        脚本管理 (注册、版本控制、语法校验)
├── monitor/        运行监控 (执行追踪、指标采集、告警管理)
├── recovery/       异常自愈 (自动重试、健康检查、死锁检测)
├── logging/        日志系统 (JSON 格式、日志轮转)
├── deploy/         部署工具 (守护进程、系统服务生成)
└── main.py         CLI 入口 (Click)
```

### 回调链

```
TaskExecutor.on_task_start  →  ExecutionTracker.on_task_start
TaskExecutor.on_task_complete  →  ExecutionTracker.on_task_complete
                                    →  AlertManager.check_and_alert
                               →  RetryManager (失败时自动重试)
```

## 编写任务脚本

任务脚本是标准的 Python 文件，通过 `python script.py` 方式调用。

项目内置了一个完整的示例脚本 [`scripts/example_task.py`](scripts/example_task.py)，核心结构如下：

```python
#!/usr/bin/env python3
"""CronCopilot 示例任务脚本。"""

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

    try:
        # ---- 在这里编写你的任务逻辑 ----
        print("  正在处理数据 ...")
        time.sleep(2)
        print("  数据处理完成")

        elapsed = time.monotonic() - start_time
        print(f"[{datetime.now().isoformat()}] 任务执行成功 (耗时: {elapsed:.2f}s)")
        return 0  # 成功

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        print(f"[{datetime.now().isoformat()}] 任务执行失败 (耗时: {elapsed:.2f}s)", file=sys.stderr)
        print(f"  错误: {exc}", file=sys.stderr)
        return 1  # 失败


if __name__ == "__main__":
    sys.exit(main())
```

**脚本规范：**

- 退出码 `0` = 成功，非 `0` = 失败
- stdout 会被记录到执行日志
- stderr 会在失败时用于告警消息

## 贡献指南

欢迎对 CronCopilot 项目提出改进建议和代码贡献！

### 开发环境设置

```bash
# 克隆仓库
git clone https://gitee.com/eden2f/cron-copilot.git
cd CronCopilot

# 安装项目及开发依赖
pip install -e ".[dev]"

# 运行测试
pytest
```

### 代码提交流程

1. **Fork** 本仓库到你的 Gitee 账号
2. **创建分支** — `git checkout -b feature/your-feature`
3. **提交更改** — `git commit -m "feat: 添加某某功能"`
4. **推送分支** — `git push origin feature/your-feature`
5. **提交 Pull Request** — 在 Gitee 上发起合并请求

### 代码规范

- 遵循 [PEP 8](https://peps.python.org/pep-0008/) 编码风格
- 新功能请添加对应的单元测试
- 更新相关文档说明

### 问题报告

提交 Issue 时请包含以下信息：

- **CronCopilot 版本：** `pip show croncopilot`
- **Python 版本：** `python --version`
- **操作系统：** 系统类型及版本
- **错误堆栈：** 完整的 traceback 输出
- **复现步骤：** 最小化的操作步骤

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
