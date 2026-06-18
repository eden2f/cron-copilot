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
- **配置热重载** — 修改配置或通过 CLI 增删改任务后自动通知调度器重载，无需重启
- **系统服务** — 自动生成 Linux (systemd) / macOS (launchd) 服务配置（Windows 仅生成启动脚本，不支持原生服务化部署）

## 系统要求

- **Python：** 3.10 及以上
- **操作系统：** Linux, macOS（原生支持）；Windows 不支持原生运行，需通过 WSL2 使用（项目依赖 `os.fork()`、`SIGTERM/SIGHUP` 等 Unix 系统机制）
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

# 安装（生产模式）【推荐】
pip install .

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

# 配置任务依赖（task-b 等待 task-a 完成后执行）
croncopilot task add \
    --name task-b \
    --script scripts/example_task.py \
    --schedule-type daily \
    --schedule "09:30" \
    --depends-on task-a

# 手动执行一次
croncopilot task run my-task

# 修改任务调度（无需重启调度器，自动热重载）
croncopilot task update my-task --schedule "0 10,18 * * *"
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

若通过 `pip install -e .` 开发模式安装，源码修改后自动生效，无需重新安装。
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
| `croncopilot start [-d/--daemon] [-f/--foreground]` | 启动调度器（默认前台运行） |
| `croncopilot stop` | 停止守护进程 |
| `croncopilot status` | 查看运行状态 |
| `croncopilot health` | 执行系统健康检查 |

### 任务管理

| 命令 | 说明 |
|------|------|
| `croncopilot task add` | 添加新任务 |
| `croncopilot task update <name> [选项]` | 更新任务配置（仅修改指定字段） |
| `croncopilot task remove <name> [-f/--force]` | 删除任务（`-f` 跳过确认） |
| `croncopilot task list [-c/--category] [-s/--status]` | 列出所有任务（支持按分类、状态过滤） |
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
| `--timeout` | 否 | `3600` | 超时时间(秒)，必须 ≥ 1 |
| `--max-retries` | 否 | `3` | 最大重试次数，必须 ≥ 0 |
| `--max-instances` | 否 | `1` | 最大并发实例数，必须 ≥ 1 |
| `--category` | 否 | `""` | 分类 |
| `--description` | 否 | `""` | 描述 |
| `--depends-on` | 否 | — | 依赖的任务名称（可多次指定） |
| `--holiday-mode` | 否 | `none` | 节假日模式 (none/workday_only/holiday_only/skip_holiday/skip_workday) |

**task update 选项：**

`task update` 只更新显式指定的字段，未指定的字段保持不变。修改完成后会自动通知运行中的调度器重新加载（见[配置热重载](#配置热重载)），无需手动重启。

| 选项 | 说明 |
|------|------|
| `--new-name` | 新任务名称 |
| `-s, --script` | 脚本路径 |
| `-t, --schedule-type` | 调度类型 (cron/daily/weekly/monthly/interval) |
| `-S, --schedule` | 调度表达式 |
| `-p, --priority` | 优先级 1-10 |
| `--timeout` | 超时时间(秒) |
| `--max-retries` | 最大重试次数 |
| `--max-instances` | 最大并发实例数 |
| `--category` | 分类（传空串清空） |
| `--description` | 描述（传空串清空） |
| `--holiday-mode` | 节假日模式 (none/workday_only/holiday_only/skip_holiday/skip_workday) |
| `--enable / --disable` | 启用/禁用任务 |

```bash
# 修改调度时间（每天 10:00 和 18:00）
croncopilot task update my-task --schedule-type cron --schedule "0 10,18 * * *"

# 调整优先级并切换为仅工作日执行
croncopilot task update my-task --priority 2 --holiday-mode workday_only

# 临时禁用任务
croncopilot task update my-task --disable
```

### 脚本管理

| 命令 | 说明 |
|------|------|
| `croncopilot script add` | 注册脚本（支持 `--venv` 指定独立虚拟环境路径） |
| `croncopilot script remove <name> [--delete-file]` | 注销脚本（`--delete-file` 同时删除脚本文件） |
| `croncopilot script update <name> [-p/--path] [选项]` | 更新脚本文件或元信息（自动备份旧版本） |
| `croncopilot script list [-c/--category]` | 列出所有脚本（支持按分类过滤） |
| `croncopilot script info <name>` | 查看脚本详情和版本历史 |

**script add 选项：**

| 选项 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `-p, --path` | 是 | — | 脚本文件路径 |
| `-n, --name` | 否 | 文件名 | 脚本名称（默认使用文件名） |
| `-a, --author` | 否 | `""` | 作者 |
| `-d, --description` | 否 | `""` | 描述 |
| `-c, --category` | 否 | `""` | 分类 |
| `--venv` | 否 | `""` | 虚拟环境路径 |

**script update 选项：**

`script update` 只更新显式指定的字段，未指定的字段保持不变。指定 `-p/--path` 时，若脚本内容有变化则自动备份旧版本。

| 选项 | 说明 |
|------|------|
| `-p, --path` | 新脚本文件路径 |
| `-a, --author` | 作者 |
| `-d, --description` | 描述（传空串清空） |
| `-c, --category` | 分类（传空串清空） |
| `--venv` | 虚拟环境路径 |

```bash
# 升级脚本文件
croncopilot script update my-script --path scripts/new_version.py

# 修改元信息
croncopilot script update my-script --author "Eden" --description "v2.0"
```

### 虚拟环境隔离

为脚本指定独立的 Python 虚拟环境，避免不同脚本间的依赖冲突：

```bash
# 创建虚拟环境
python -m venv ~/.croncopilot/venvs/my-script-env
~/.croncopilot/venvs/my-script-env/bin/pip install requests pandas

# 注册脚本并关联虚拟环境
croncopilot script add \
    --path scripts/data_fetch.py \
    --name data-fetch \
    --venv ~/.croncopilot/venvs/my-script-env
```

指定虚拟环境后，CronCopilot 将使用该环境中的 Python 解释器执行脚本，确保依赖隔离。

### 任务执行历史

```bash
# 查看最近 30 天的执行记录和统计
croncopilot task history <name>

# 查看最近 7 天，显示 50 条记录（支持短选项）
croncopilot task history <name> -d 7 -l 50

# 仅查看统计摘要
croncopilot task history <name> --stats-only
```

**task history 选项：**

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-d, --days` | `30` | 查看最近 N 天的记录 |
| `-l, --limit` | `20` | 显示最近 N 条执行记录 |
| `--stats-only` | — | 仅显示统计摘要 |

### 调度表达式格式

| 类型 | 格式 | 示例 |
|------|------|------|
| `cron` | 标准 5 段 cron | `0 8 * * *` (每天 8:00) |
| `daily` | `HH:MM` | `08:00` |
| `weekly` | `day@HH:MM` | `mon@08:00` (每周一 8:00) |
| `monthly` | `day@HH:MM` | `1@08:00` (每月 1 日 8:00) |
| `interval` | `<数字><单位>` | `30m`, `2h`, `1d`, `90s` |

> **cron 表达式格式：** `分钟 小时 日期 月份 星期`，例如 `0 9 * * 1-5` 表示周一至周五 9:00 执行。

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

> **启用邮件告警：** 将 `alert.email.enabled` 设为 `true`，填写 SMTP 服务器信息和收件人列表。配置完成后，任务失败时系统将自动发送告警邮件。常见 SMTP 配置示例：Gmail（`smtp.gmail.com:587`）、QQ邮箱（`smtp.qq.com:587`）。

## 配置热重载

CronCopilot 支持两类热重载，均无需重启服务：

**1. 配置文件热重载** — 修改 `config.yaml` 后，发送 `SIGHUP` 信号即可生效（watchdog 也会自动监听文件变化并触发重载）：

```bash
kill -HUP $(cat ~/.croncopilot/croncopilot.pid)
```

**2. 任务热重载** — 通过 CLI 执行 `task add` / `task update` / `task remove` 后，会自动通过 PID 文件向运行中的调度器发送 `SIGHUP`，调度器收到后从数据库重新加载全部任务。因此任务的增删改均可即时生效，无需手动重启或手动发信号。

> 若调度器未运行，CLI 会提示「修改将在下次启动时生效」——配置已写入数据库，下次 `croncopilot start` 时自动加载。

**生效范围：**

- 调度器参数（线程池大小、时区等）
- 告警设置（阈值、邮件配置等）
- 日志级别
- 任务的调度参数、节假日模式、启停状态等（含任务的新增/删除/更新，由 `task add/update/remove` 自动触发重载）

**不支持热重载的操作：**

- 数据库路径变更 — 需重启服务

## 系统服务部署

### 方式一：使用内置生成器（推荐）

```python
from croncopilot.deploy.service import ServiceGenerator

generator = ServiceGenerator()
generator.install_service()  # 自动检测平台、填充路径并安装服务
```

`ServiceGenerator` 会自动检测当前平台（Linux/macOS），并填充用户名、Python 解释器路径、Home 目录等信息，生成可直接使用的服务配置文件，同时打印后续安装命令供手动执行。

### 方式二：手动部署模板文件

如需手动控制服务配置，可使用 `deploy/` 目录下的模板文件，但需要手动替换其中的占位符。

**Linux (systemd)：**

```bash
sudo cp deploy/croncopilot.service /etc/systemd/system/
# 编辑文件，将 %USER%, %PYTHON%, %HOME% 替换为实际值
sudo vim /etc/systemd/system/croncopilot.service
sudo systemctl daemon-reload
sudo systemctl enable croncopilot
sudo systemctl start croncopilot
```

**macOS (launchd)：**

```bash
cp deploy/com.croncopilot.plist ~/Library/LaunchAgents/
# 编辑文件，将 %PYTHON%, %HOME% 替换为实际值
vim ~/Library/LaunchAgents/com.croncopilot.plist
launchctl load ~/Library/LaunchAgents/com.croncopilot.plist
```

## 架构说明

```text
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

```text
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

**执行环境：**

- 脚本通过子进程方式执行（`python script.py`），与 CronCopilot 主进程隔离
- 如果脚本关联了虚拟环境，将使用该环境的 Python 解释器
- 脚本超时时间通过 `--timeout` 参数配置（默认 3600 秒），超时后进程将被终止

## 常见问题与故障排除

### 日志在哪里？

默认日志目录为 `~/.croncopilot/logs/`，可在 `config.yaml` 中通过 `log.log_dir` 修改。查看最新日志：

```bash
# 查看调度器日志
ls -lt ~/.croncopilot/logs/
tail -f ~/.croncopilot/logs/croncopilot.log
```

### 启动失败怎么办？

1. **PID 文件冲突** — 如果上次异常退出留下了 PID 文件，删除后重试：

   ```bash
   rm ~/.croncopilot/croncopilot.pid
   croncopilot start --daemon
   ```

2. **端口/进程占用** — 检查是否有残留进程：

   ```bash
   croncopilot status
   # 如显示已运行，先停止
   croncopilot stop
   ```

3. **配置文件错误** — 检查 YAML 语法：

   ```bash
   python -c "import yaml; yaml.safe_load(open('~/.croncopilot/config.yaml'.replace('~', __import__('os').path.expanduser('~'))))"
   ```

### 任务执行失败如何排查？

```bash
# 查看任务执行历史和失败统计
croncopilot task history <task-name>

# 查看最近 7 天、显示 50 条记录
croncopilot task history <task-name> -d 7 -l 50

# 查看系统健康状态
croncopilot health
```

失败的 stderr 输出会记录在执行日志中，同时触发告警通知（如已配置）。

### 配置路径中的 `~` 是什么意思？

配置文件中的路径支持 `~` 符号表示用户主目录，系统启动时会自动展开。例如 `~/.croncopilot/data.db` 会展开为 `/home/username/.croncopilot/data.db`。

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
