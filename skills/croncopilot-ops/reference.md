# CronCopilot 详细参考

> **项目仓库:** [Gitee](https://gitee.com/eden2f/cron-copilot) | [GitHub](https://github.com/eden2f/cron-copilot)    **协议:** MIT    **Python:** ≥3.10
>
> 安装：`git clone https://gitee.com/eden2f/cron-copilot.git && cd CronCopilot && pip install -e . && croncopilot init`

---

## A. 全局选项

| 选项 | 说明 |
|------|------|
| `--config / -c <path>` | 指定配置文件路径，默认 `~/.croncopilot/config.yaml` |
| `--verbose / -v` | 启用详细输出 |

用法示例：

```bash
croncopilot -c /path/to/config.yaml task list
croncopilot -v start
```

---

## B. 各命令完整参数说明

### init

```bash
croncopilot init
```

创建 `~/.croncopilot/` 目录结构、生成默认配置文件、初始化 SQLite 数据库。无额外参数。

---

### start

```bash
croncopilot start [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--daemon / -d` | 以守护进程模式运行（后台） |
| `--foreground / -f` | 前台运行（默认） |

启动后自动写入 PID 文件到 `~/.croncopilot/croncopilot.pid`。

---

### stop

```bash
croncopilot stop
```

读取 PID 文件并发送 SIGTERM 信号停止守护进程。无额外参数。

---

### status

```bash
croncopilot status
```

显示运行状态（PID、是否存活）和已注册任务列表。无额外参数。

---

### health

```bash
croncopilot health
```

执行系统健康检查，输出 CPU / 内存 / 磁盘使用率和对应阈值。无额外参数。

---

### task add

```bash
croncopilot task add [OPTIONS]
```

| 选项 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `-n, --name TEXT` | 是 | — | 任务名称（唯一标识） |
| `-s, --script TEXT` | 是 | — | 脚本文件路径（必须存在） |
| `-t, --schedule-type` | 是 | — | 调度类型：`cron` / `daily` / `weekly` / `monthly` / `interval` |
| `-S, --schedule TEXT` | 是 | — | 调度表达式（格式取决于 schedule-type） |
| `-p, --priority INT` | 否 | `5` | 优先级 1-10（1 最高，10 最低） |
| `--timeout INT` | 否 | `3600` | 任务超时时间（秒） |
| `--max-retries INT` | 否 | `3` | 失败后最大重试次数 |
| `--category TEXT` | 否 | `""` | 分类标签（用于过滤和分组） |
| `--description TEXT` | 否 | `""` | 任务描述 |
| `--depends-on TEXT` | 否 | — | 依赖的任务名称（可多次指定） |
| `--holiday-mode` | 否 | `none` | 节假日模式：`none` / `workday_only` / `holiday_only` / `skip_holiday` / `skip_workday` |

**示例：**

```bash
# 基本 cron 任务
croncopilot task add -n backup \
    -s scripts/backup.py -t cron -S "0 2 * * *"

# 工作日每日报表，高优先级
croncopilot task add -n daily-report \
    -s scripts/report.py -t daily -S "09:00" \
    -p 1 --holiday-mode workday_only \
    --category report --description "每日业务报表"

# 带依赖的任务
croncopilot task add -n send-report \
    -s scripts/send.py -t daily -S "09:30" \
    --depends-on daily-report

# 每 30 秒执行的高频任务
croncopilot task add -n heartbeat \
    -s scripts/heartbeat.py -t interval -S "30s" \
    --timeout 20 --max-retries 1
```

---

### task list

```bash
croncopilot task list [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `-c, --category TEXT` | 按分类过滤 |
| `-s, --status TEXT` | 按状态过滤（`enabled` / `disabled`） |

输出字段：名称、类型、调度表达式、优先级、状态、节假日模式、分类。

---

### task run

```bash
croncopilot task run <name>
```

立即执行指定任务一次（同步等待完成），不影响正常调度。适用于测试和手动触发。

---

### task remove

```bash
croncopilot task remove <name> [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--force / -f` | 跳过确认直接删除 |

---

### task history

```bash
croncopilot task history <name> [OPTIONS]
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-d, --days INT` | `30` | 查看最近 N 天的记录 |
| `-l, --limit INT` | `20` | 显示最近 N 条执行记录 |
| `--stats-only` | — | 仅显示统计摘要（不显示逐条记录） |

**统计信息包括：** 总执行次数、成功/失败次数及比率、平均/最大/P95 耗时、最后执行时间和状态。

---

### script add

```bash
croncopilot script add [OPTIONS]
```

| 选项 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `-p, --path TEXT` | 是 | — | 脚本文件路径 |
| `-n, --name TEXT` | 否 | 文件名 | 脚本名称 |
| `-a, --author TEXT` | 否 | `""` | 作者 |
| `-d, --description TEXT` | 否 | `""` | 描述 |
| `-c, --category TEXT` | 否 | `""` | 分类 |
| `--venv TEXT` | 否 | `""` | 虚拟环境路径 |

注册时会自动：校验脚本语法、复制到脚本仓库、创建版本备份、计算文件哈希。

---

### script list

```bash
croncopilot script list [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `-c, --category TEXT` | 按分类过滤 |

输出字段：名称、作者、分类、版本数、路径。

---

### script info

```bash
croncopilot script info <name>
```

显示脚本详细信息：名称、路径、作者、描述、分类、虚拟环境、文件哈希、版本数、创建/更新时间、版本历史。

---

### script remove

```bash
croncopilot script remove <name> [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--delete-file` | 同时删除脚本文件（默认仅注销元数据） |

---

## C. 配置文件完整参考

配置文件路径：`~/.croncopilot/config.yaml`（`croncopilot init` 自动生成）

```yaml
# =============================================================================
# CronCopilot 配置文件
# =============================================================================

# 调度器配置
scheduler:
  max_workers: 4          # 线程池最大工作线程数（>= 1）
  max_instances: 1        # 同一任务最大并发实例数（>= 1）
  timezone: "Asia/Shanghai"  # 时区

# 数据库存储配置
storage:
  db_path: "~/.croncopilot/data.db"  # SQLite 数据库路径

# 日志配置
log:
  log_dir: "~/.croncopilot/logs"  # 日志目录
  level: "INFO"           # 日志级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
  max_days: 30            # 日志保留天数（>= 1）
  json_format: true       # 是否使用 JSON 结构化输出

# 告警配置
alert:
  failure_immediate: true              # 任务失败后立即告警
  consecutive_failure_threshold: 3     # 连续失败 N 次后触发告警（>= 1）
  cooldown_seconds: 300                # 同一任务告警冷却时间（秒，>= 0）

  # 邮件告警渠道
  email:
    enabled: false         # 是否启用邮件告警
    smtp_host: ""          # SMTP 服务器地址（启用时必填）
    smtp_port: 587         # SMTP 端口
    use_tls: true          # 是否使用 TLS 加密
    username: ""           # SMTP 用户名
    password: ""           # SMTP 密码
    sender: ""             # 发件人地址
    recipients: []         # 收件人列表（启用时不能为空）

# 恢复与健康检查配置
recovery:
  max_retries: 3          # 任务失败最大重试次数（>= 0）
  retry_delay: 10.0       # 重试初始延迟秒数（>= 0）
  backoff_factor: 2.0     # 指数退避因子（>= 1.0）
  health_check_interval: 60  # 健康检查间隔秒数
  cpu_threshold: 90.0     # CPU 使用率告警阈值（0-100）
  memory_threshold: 90.0  # 内存使用率告警阈值（0-100）
  disk_threshold: 90.0    # 磁盘使用率告警阈值（0-100）
  task_timeout: 3600      # 全局任务超时时间秒数（>= 1）

# 脚本管理配置
script:
  script_dir: "~/.croncopilot/scripts"              # 脚本仓库目录
  version_dir: "~/.croncopilot/script_versions"     # 脚本版本备份目录
  max_versions: 10        # 每个脚本最大保留版本数（>= 1）

# PID 文件路径
pid_file: "~/.croncopilot/croncopilot.pid"
```

---

## D. 调度表达式完整参考

### cron（5 段格式）

格式：`分钟 小时 日 月 星期`

| 字段 | 范围 | 特殊符号 |
|------|------|---------|
| 分钟 | 0-59 | `*` `,` `-` `/` |
| 小时 | 0-23 | `*` `,` `-` `/` |
| 日 | 1-31 | `*` `,` `-` `/` |
| 月 | 1-12 | `*` `,` `-` `/` |
| 星期 | 0-6（0=周日）或 `mon`-`sun` | `*` `,` `-` `/` |

**符号说明：**

| 符号 | 含义 | 示例 |
|------|------|------|
| `*` | 任意值 | `* * * * *`（每分钟） |
| `,` | 列举 | `0,30 * * * *`（每小时 0 分和 30 分） |
| `-` | 范围 | `0 9-17 * * *`（9 点到 17 点整点） |
| `/` | 步长 | `*/5 * * * *`（每 5 分钟） |

**常用示例：**

```
0 8 * * *          每天 8:00
0 8 * * 1-5        周一到周五 8:00
0 */2 * * *        每 2 小时整点
30 9 1 * *         每月 1 日 9:30
0 0 * * 0          每周日 0:00
*/10 * * * *       每 10 分钟
0 9,18 * * *       每天 9:00 和 18:00
```

### daily

格式：`HH:MM`

```
09:00              每天 09:00
23:30              每天 23:30
```

### weekly

格式：`day@HH:MM`（day = `mon`/`tue`/`wed`/`thu`/`fri`/`sat`/`sun`）

```
mon@08:00          每周一 08:00
fri@17:30          每周五 17:30
```

### monthly

格式：`day@HH:MM`（day = 1-31）

```
1@08:00            每月 1 日 08:00
15@12:00           每月 15 日 12:00
```

### interval

格式：`<N><unit>`（unit = `s`/`m`/`h`/`d`）

| 单位 | 含义 |
|------|------|
| `s` | 秒 |
| `m` | 分钟 |
| `h` | 小时 |
| `d` | 天 |

```
30s                每 30 秒
5m                 每 5 分钟
2h                 每 2 小时
1d                 每天
```

---

## E. 任务脚本完整模板

```python
#!/usr/bin/env python3
"""CronCopilot 任务脚本模板。

兼容性要求：
- 必须包含 main() 函数，返回 int（0=成功，非0=失败）
- 入口：if __name__ == "__main__": sys.exit(main())
- stdout 输出记录为日志
- stderr 输出用于失败告警
"""

from __future__ import annotations

import sys
import time
from datetime import datetime


def main() -> int:
    """任务主函数。

    Returns:
        退出码：0 表示成功，1 表示失败。
    """
    start_time = time.monotonic()
    print(f"[{datetime.now().isoformat()}] 任务开始执行")

    try:
        # ---- 在这里编写你的任务逻辑 ----

        # 示例：模拟数据处理
        print("  正在处理数据 ...")
        time.sleep(2)
        print("  数据处理完成")

        # ---- 任务逻辑结束 ----

        elapsed = time.monotonic() - start_time
        print(f"[{datetime.now().isoformat()}] 任务执行成功 (耗时: {elapsed:.2f}s)")
        return 0

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        print(
            f"[{datetime.now().isoformat()}] 任务执行失败 (耗时: {elapsed:.2f}s)",
            file=sys.stderr,
        )
        print(f"  错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

---

## F. 部署详细步骤

### Linux systemd

**服务文件模板** (`deploy/croncopilot.service`)：

```ini
[Unit]
Description=CronCopilot - Python Task Scheduler
After=network.target

[Service]
Type=simple
User=%USER%
ExecStart=%PYTHON% -m croncopilot start --foreground
WorkingDirectory=%HOME%
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**部署步骤：**

```bash
# 1. 复制并替换占位符
sudo cp deploy/croncopilot.service /etc/systemd/system/
sudo sed -i "s|%USER%|$(whoami)|g" /etc/systemd/system/croncopilot.service
sudo sed -i "s|%PYTHON%|$(which python3)|g" /etc/systemd/system/croncopilot.service
sudo sed -i "s|%HOME%|$HOME|g" /etc/systemd/system/croncopilot.service

# 2. 重载 systemd 并启用
sudo systemctl daemon-reload
sudo systemctl enable croncopilot
sudo systemctl start croncopilot

# 3. 查看状态
sudo systemctl status croncopilot

# 4. 查看日志
journalctl -u croncopilot -f
```

### macOS launchd

**plist 文件模板** (`deploy/com.croncopilot.plist`)：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.croncopilot</string>

    <key>ProgramArguments</key>
    <array>
        <string>%PYTHON%</string>
        <string>-m</string>
        <string>croncopilot</string>
        <string>start</string>
        <string>--foreground</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>%HOME%/.croncopilot/logs/launchd_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>%HOME%/.croncopilot/logs/launchd_stderr.log</string>

    <key>WorkingDirectory</key>
    <string>%HOME%</string>
</dict>
</plist>
```

**部署步骤：**

```bash
# 1. 复制并替换占位符
cp deploy/com.croncopilot.plist ~/Library/LaunchAgents/
sed -i '' "s|%PYTHON%|$(which python3)|g" ~/Library/LaunchAgents/com.croncopilot.plist
sed -i '' "s|%HOME%|$HOME|g" ~/Library/LaunchAgents/com.croncopilot.plist

# 2. 加载服务（开机自启）
launchctl load ~/Library/LaunchAgents/com.croncopilot.plist

# 3. 卸载服务
launchctl unload ~/Library/LaunchAgents/com.croncopilot.plist

# 4. 查看服务状态
launchctl list | grep croncopilot
```

> **重要提醒：** plist 文件中的占位符（`%PYTHON%`、`%HOME%`）必须在部署前全部替换为真实路径，否则 `launchctl load` 虽无报错但服务不会正常启用。

---

## G. 信号处理

| 信号 | 行为 |
|------|------|
| `SIGINT` (`Ctrl+C`) | 优雅关闭：停止接受新任务，等待运行中任务完成，清理 PID 文件 |
| `SIGTERM` | 同 SIGINT，用于 `croncopilot stop` 或系统服务停止 |
| `SIGHUP` | 热重载配置文件：重新读取 `config.yaml` 并刷新任务调度 |

**热重载用法：**

```bash
# 修改配置后手动触发重载
kill -HUP $(cat ~/.croncopilot/croncopilot.pid)
```

配置文件修改后也会被自动监控并触发重载（文件监听模式）。

---

## H. 目录结构

```
~/.croncopilot/
├── config.yaml            # 主配置文件（YAML 格式）
├── data.db                # SQLite 数据库（任务、脚本、执行记录）
├── croncopilot.pid        # 守护进程 PID 文件
├── logs/                  # 日志目录
│   ├── croncopilot.log    # 当前日志文件（JSON 格式）
│   ├── croncopilot.log.2025-01-01  # 按天轮转的历史日志
│   ├── launchd_stdout.log # macOS launchd 标准输出
│   └── launchd_stderr.log # macOS launchd 标准错误
├── scripts/               # 脚本仓库（注册的脚本副本）
└── script_versions/       # 脚本版本备份（自动管理）
    └── <script_name>/     # 每个脚本一个子目录
        ├── <hash>_<timestamp>.py  # 历史版本文件
        └── ...
```

**说明：**

- `config.yaml`：由 `croncopilot init` 生成，支持运行时热重载
- `data.db`：SQLAlchemy + SQLite，存储任务定义、脚本元数据、执行记录
- `logs/`：按天分割，超过 `max_days` 天的日志自动清理
- `scripts/`：注册脚本时自动复制到此目录
- `script_versions/`：每次脚本更新自动备份，最多保留 `max_versions` 个版本
