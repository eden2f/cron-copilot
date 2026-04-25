---
name: pycronguard-ops
description: PyCronGuard 定时任务管理系统的运维使用指南。包含安装部署、任务管理、脚本编写、节假日配置和监控告警。Use when users ask about managing scheduled tasks with PyCronGuard, adding cron jobs, deploying PyCronGuard as a system service, or configuring holiday-aware scheduling.
---

# PyCronGuard 运维使用指南

## 项目简介

PyCronGuard 是一个 Python 定时任务管理与监控系统，支持 cron 表达式、节假日感知、异常自愈、系统服务部署。

- **Gitee:** https://gitee.com/eden2f/py-cron-guard
- **GitHub:** https://github.com/eden2f/py-cron-guard
- **开源协议:** MIT License

## 环境要求

- Python 3.10+
- 支持 Linux、macOS（Windows 可通过 WSL2）

## 安装步骤（从零开始）

```bash
# 克隆项目
git clone https://gitee.com/eden2f/py-cron-guard.git
cd PyCronGuard

# 安装
pip install -e .

# 初始化（首次使用必须执行）
pycronguard init
```

初始化后的目录结构：

```
~/.pycronguard/
├── config.yaml          # 配置文件
├── data.db              # SQLite 数据库
├── logs/                # 日志目录
├── scripts/             # 任务脚本目录
├── script_versions/     # 脚本版本备份
└── pycronguard.pid      # PID 文件
```

**核心依赖：**
- `apscheduler` — 任务调度引擎
- `sqlalchemy` — 数据存储
- `click` — CLI 框架
- `chinesecalendar` — 中国节假日识别

---

## 快速上手

标准工作流：**编写脚本 → 注册脚本 → 创建任务 → 启动调度器**

```bash
# 1. 注册脚本
pycronguard script add --path scripts/my_task.py --name my-task

# 2. 创建任务
pycronguard task add -n my-task -s scripts/my_task.py -t daily -S "09:00"

# 3. 测试执行
pycronguard task run my-task

# 4. 启动调度器
pycronguard start          # 前台运行
pycronguard start -d       # 守护进程模式
```

---

## CLI 命令速查表

| 命令 | 说明 |
|------|------|
| `pycronguard init` | 初始化配置和目录 |
| `pycronguard start [-d]` | 启动调度器（`-d` 守护进程） |
| `pycronguard stop` | 停止守护进程 |
| `pycronguard status` | 查看运行状态 |
| `pycronguard health` | 系统健康检查 |
| `pycronguard task add` | 添加定时任务 |
| `pycronguard task list` | 列出任务 |
| `pycronguard task run <name>` | 立即执行任务 |
| `pycronguard task remove <name>` | 删除任务 |
| `pycronguard task history <name>` | 查看执行历史 |
| `pycronguard script add` | 注册脚本 |
| `pycronguard script list` | 列出脚本 |
| `pycronguard script info <name>` | 查看脚本详情 |
| `pycronguard script remove <name>` | 注销脚本 |

全局选项：`--config / -c` 指定配置文件路径，`--verbose / -v` 详细输出。

---

## task add 核心参数

| 选项 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `-n, --name` | 是 | — | 任务名称 |
| `-s, --script` | 是 | — | 脚本路径 |
| `-t, --schedule-type` | 是 | — | `cron` / `daily` / `weekly` / `monthly` / `interval` |
| `-S, --schedule` | 是 | — | 调度表达式（见下方速查） |
| `-p, --priority` | 否 | 5 | 优先级 1-10（1 最高） |
| `--timeout` | 否 | 3600 | 超时秒数 |
| `--max-retries` | 否 | 3 | 最大重试次数 |
| `--holiday-mode` | 否 | `none` | `none` / `workday_only` / `holiday_only` / `skip_holiday` / `skip_workday` |
| `--depends-on` | 否 | — | 依赖任务名（可多次指定） |
| `--category` | 否 | — | 分类标签 |
| `--description` | 否 | — | 任务描述 |

---

## 调度表达式速查

| 类型 | 格式 | 示例 |
|------|------|------|
| `cron` | `min hour day month dow` | `0 8 * * *`（每天 8:00）、`*/5 * * * *`（每 5 分钟） |
| `daily` | `HH:MM` | `09:00` |
| `weekly` | `day@HH:MM` | `mon@08:00`（每周一 8:00） |
| `monthly` | `day@HH:MM` | `1@08:00`（每月 1 日 8:00） |
| `interval` | `<N><unit>` | `5m`、`2h`、`1d`、`90s` |

**interval 单位：** `s`=秒，`m`=分钟，`h`=小时，`d`=天。

**cron 特殊符号：** `*`=任意值，`,`=列举，`-`=范围，`/`=步长。

---

## 任务脚本规范

必须满足以下约定：

1. 包含 `main()` 函数，返回 `int`（`0` = 成功，非 `0` = 失败）
2. 入口代码：`if __name__ == "__main__": sys.exit(main())`
3. `stdout` 输出会被记录为日志，`stderr` 输出用于失败告警

**最小模板：**

```python
#!/usr/bin/env python3
import sys

def main() -> int:
    try:
        # 你的任务逻辑
        print("任务执行成功")
        return 0
    except Exception as exc:
        print(f"任务失败: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

---

## 节假日模式一览

基于 `chinesecalendar` 库实现中国法定节假日和调休识别。

| 模式 | 执行条件 |
|------|---------|
| `none` | 每天执行（默认） |
| `workday_only` | 仅工作日执行（含调休上班日） |
| `holiday_only` | 仅节假日和周末执行 |
| `skip_holiday` | 常规调度，遇法定节假日跳过 |
| `skip_workday` | 常规调度，遇工作日跳过 |

使用示例：

```bash
# 仅工作日执行的每日报表
pycronguard task add -n daily-report \
    -s scripts/report.py -t daily -S "09:00" \
    --holiday-mode workday_only
```

---

## 常用操作示例

```bash
# 添加每 5 分钟执行的监控任务
pycronguard task add -n health-check \
    -s scripts/check.py -t interval -S "5m"

# 添加带依赖的任务（B 依赖 A 完成后才执行）
pycronguard task add -n task-b \
    -s scripts/b.py -t daily -S "10:00" \
    --depends-on task-a

# 查看任务列表
pycronguard task list

# 按分类过滤
pycronguard task list --category report

# 立即测试执行
pycronguard task run daily-report

# 查看最近执行统计
pycronguard task history daily-report --stats-only

# 查看最近 7 天、最多 50 条记录
pycronguard task history daily-report --days 7 --limit 50

# 强制删除任务（不需确认）
pycronguard task remove old-task --force

# 注册脚本（带元信息）
pycronguard script add --path scripts/report.py \
    --name report --author "ops-team" \
    --description "每日报表生成" --category report

# 查看脚本详情和版本历史
pycronguard script info report

# 注销脚本并删除文件
pycronguard script remove report --delete-file

# 配置热重载（发送 SIGHUP 信号）
kill -HUP $(cat ~/.pycronguard/pycronguard.pid)

# 系统健康检查
pycronguard health
```

---

## 部署为系统服务

### Linux (systemd)

```bash
# 1. 复制服务文件
sudo cp deploy/pycronguard.service /etc/systemd/system/

# 2. 替换占位符（必须替换，否则服务无法启动）
sudo sed -i "s|%USER%|$(whoami)|g" /etc/systemd/system/pycronguard.service
sudo sed -i "s|%PYTHON%|$(which python3)|g" /etc/systemd/system/pycronguard.service
sudo sed -i "s|%HOME%|$HOME|g" /etc/systemd/system/pycronguard.service

# 3. 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable pycronguard
sudo systemctl start pycronguard
```

### macOS (launchd)

```bash
# 1. 复制 plist 文件
cp deploy/com.pycronguard.plist ~/Library/LaunchAgents/

# 2. 替换占位符（必须替换，否则服务无法正常工作）
sed -i '' "s|%PYTHON%|$(which python3)|g" ~/Library/LaunchAgents/com.pycronguard.plist
sed -i '' "s|%HOME%|$HOME|g" ~/Library/LaunchAgents/com.pycronguard.plist

# 3. 加载服务
launchctl load ~/Library/LaunchAgents/com.pycronguard.plist
```

> **注意：** plist 文件中的占位符必须在部署前全部替换为真实路径，否则 `launchctl load` 虽无报错但服务不会正常启用。

---

## 信号处理

| 信号 | 行为 |
|------|------|
| `SIGINT` / `SIGTERM` | 优雅关闭（等待运行中任务完成） |
| `SIGHUP` | 热重载配置文件 |

---

## 更多参考

完整 CLI 参数、配置文件字段和部署模板，见 [reference.md](reference.md)。
