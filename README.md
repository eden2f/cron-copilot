# PyCronGuard

**PyCronGuard** 是一个功能完备的 Python 定时任务管理与监控系统，提供任务调度、脚本管理、运行监控、告警通知和异常自愈等能力。

## 功能特性

- **灵活调度** — 支持 cron 表达式、每日/每周/每月/间隔等多种调度方式
- **优先级队列** — 基于堆的任务优先级排序，支持并发控制和依赖管理
- **脚本管理** — 脚本注册、版本控制、语法校验、自动备份
- **实时监控** — 任务执行追踪、系统资源指标采集 (CPU/内存/磁盘)
- **智能告警** — 即时失败告警、连续失败告警、性能阈值告警，支持邮件通知
- **异常自愈** — 自动重试 (指数退避)、健康检查、死锁检测与自动终止
- **守护进程** — 支持前台/后台运行，PID 管理，优雅关闭
- **配置热加载** — YAML 配置文件修改后自动重载
- **系统服务** — 自动生成 systemd / launchd / Windows 服务配置

## 快速开始

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd PyCronGuard

# 安装（开发模式）
pip install -e .

# 安装开发依赖
pip install -e ".[dev]"
```

### 初始化

```bash
# 创建目录结构和默认配置
pycronguard init
```

这将在 `~/.pycronguard/` 下创建：
- `config.yaml` — 配置文件
- `data.db` — SQLite 数据库
- `logs/` — 日志目录
- `scripts/` — 脚本目录
- `script_versions/` — 脚本版本备份

### 添加任务

```bash
# 注册脚本
pycronguard script add --path scripts/example_task.py --name example

# 添加定时任务（每 5 分钟执行）
pycronguard task add \
    --name my-task \
    --script scripts/example_task.py \
    --schedule-type interval \
    --schedule 5m

# 添加 cron 任务（每天 8:00）
pycronguard task add \
    --name daily-report \
    --script scripts/example_task.py \
    --schedule-type daily \
    --schedule "08:00"

# 手动执行一次
pycronguard task run my-task
```

### 启动调度器

```bash
# 前台运行
pycronguard start

# 后台守护进程
pycronguard start --daemon

# 查看状态
pycronguard status

# 停止
pycronguard stop
```

## CLI 命令参考

### 全局选项

| 选项 | 说明 |
|------|------|
| `-c, --config PATH` | 指定配置文件路径 |
| `-v, --verbose` | 详细输出 |

### 核心命令

| 命令 | 说明 |
|------|------|
| `pycronguard init` | 初始化配置和目录结构 |
| `pycronguard start [-d\|--daemon]` | 启动调度器 |
| `pycronguard stop` | 停止守护进程 |
| `pycronguard status` | 查看运行状态 |
| `pycronguard health` | 执行系统健康检查 |

### 任务管理

| 命令 | 说明 |
|------|------|
| `pycronguard task add` | 添加新任务 |
| `pycronguard task remove <name>` | 删除任务 |
| `pycronguard task list` | 列出所有任务 |
| `pycronguard task run <name>` | 立即执行一次任务 |

**task add 选项：**

| 选项 | 必填 | 说明 |
|------|------|------|
| `-n, --name` | 是 | 任务名称 |
| `-s, --script` | 是 | 脚本路径 |
| `-t, --schedule-type` | 是 | 调度类型 (cron/daily/weekly/monthly/interval) |
| `-S, --schedule` | 是 | 调度表达式 |
| `-p, --priority` | 否 | 优先级 1-10，默认 5 |
| `--timeout` | 否 | 超时时间(秒)，默认 3600 |
| `--max-retries` | 否 | 最大重试次数，默认 3 |
| `--category` | 否 | 分类 |
| `--description` | 否 | 描述 |
| `--depends-on` | 否 | 依赖的任务名称（可多次指定） |

### 脚本管理

| 命令 | 说明 |
|------|------|
| `pycronguard script add` | 注册脚本 |
| `pycronguard script remove <name>` | 注销脚本 |
| `pycronguard script list` | 列出所有脚本 |
| `pycronguard script info <name>` | 查看脚本详情和版本历史 |

### 调度表达式格式

| 类型 | 格式 | 示例 |
|------|------|------|
| `cron` | 标准 5 段 cron | `0 8 * * *` (每天 8:00) |
| `daily` | `HH:MM` | `08:00` |
| `weekly` | `day@HH:MM` | `mon@08:00` (每周一 8:00) |
| `monthly` | `day@HH:MM` | `1@08:00` (每月 1 日 8:00) |
| `interval` | `<数字><单位>` | `30m`, `2h`, `1d`, `90s` |

## 配置文件说明

配置文件位于 `~/.pycronguard/config.yaml`，支持以下配置项：

```yaml
# 调度器配置
scheduler:
  max_workers: 4          # 线程池最大工作线程数
  max_instances: 1        # 同一任务最大并发实例数
  timezone: "Asia/Shanghai"

# 数据库存储配置
storage:
  db_path: "~/.pycronguard/data.db"

# 日志配置
log:
  log_dir: "~/.pycronguard/logs"
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
  script_dir: "~/.pycronguard/scripts"
  version_dir: "~/.pycronguard/script_versions"
  max_versions: 10

# PID 文件
pid_file: "~/.pycronguard/pycronguard.pid"
```

## 系统服务部署

### Linux (systemd)

```bash
# 生成服务文件（自动检测平台）
# 或直接使用 deploy/pycronguard.service 模板

sudo cp deploy/pycronguard.service /etc/systemd/system/
# 编辑文件替换 %USER%, %PYTHON%, %HOME% 占位符
sudo systemctl daemon-reload
sudo systemctl enable pycronguard
sudo systemctl start pycronguard
```

### macOS (launchd)

```bash
cp deploy/com.pycronguard.plist ~/Library/LaunchAgents/
# 编辑文件替换 %PYTHON%, %HOME% 占位符
launchctl load ~/Library/LaunchAgents/com.pycronguard.plist
```

### 使用内置生成器

```python
from pycronguard.deploy.service import ServiceGenerator

generator = ServiceGenerator()
generator.install_service()  # 自动检测平台并生成配置
```

## 架构说明

```
PyCronGuard
├── config/         配置管理 (YAML 加载、Schema 校验、热加载)
├── core/           核心调度 (APScheduler 集成、任务执行器、优先级队列)
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

任务脚本是标准的 Python 文件，通过 `python script.py` 方式调用：

```python
#!/usr/bin/env python3
import sys

def main():
    # 你的任务逻辑
    print("任务执行中 ...")
    return 0  # 返回 0 表示成功

if __name__ == "__main__":
    sys.exit(main())
```

- 退出码 `0` = 成功，非 `0` = 失败
- stdout 会被记录到执行日志
- stderr 会在失败时用于告警消息

## 许可证

MIT License
