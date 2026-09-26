# 系统架构

## 组件

```text
┌──────────────────────── Chrome 扩展 ────────────────────────┐
│ popup：实时状态        service worker：每分钟徽标刷新       │
└─────────────────────────────┬───────────────────────────────┘
                              │ GET /api/extension/status
                              │ Origin 严格白名单
                              ▼
┌────────────── 127.0.0.1:18765 / Dashboard ─────────────────┐
│ server.py                                                   │
│  ├─ HTTP、Origin/Host 边界和 API 投影                       │
│  ├─ system_metrics.py：系统、进程和 launchd 只读指标         │
│  ├─ 只读扩展 API                                            │
│  ├─ 完整本机面板                                            │
│  └─ 主动清理 API → cleanup.py（扫描、确认、执行）           │
└─────────────────┬──────────────────────────────┬────────────┘
                  │ 读取状态                    │ 共享文件锁
                  ▼                             ▼
       disk-guard LaunchAgent          resource-guard LaunchAgent
       低空间白名单自动清理             临时测试进程保守治理
```

## 责任边界

### Chrome 扩展

- 只读取 `/api/extension/status`
- 显示磁盘、CPU、内存、Swap 和自动清理状态
- 每分钟刷新徽标
- 打开完整本机仪表盘
- 不拥有文件删除 API
- 不读取浏览历史、Cookie、网页或下载记录

### Dashboard Companion

- 仅监听 `127.0.0.1`
- `/api/status` 为完整本机面板提供数据
- `/api/extension/status` 返回收敛后的只读状态
- 主动清理仅接受同源页面 POST
- 扩展 Origin 只能读取状态，不能跨站调用清理

### 磁盘守护

- 每 60 秒检测 `/System/Volumes/Data` 可用空间
- 低于触发线进入压力态
- 按固定白名单逐组清理
- 达到恢复线立即停止
- 通过共享文件锁与主动清理互斥

### 资源守护

- 采集 CPU、内存和 Swap 压力
- 只跟踪当前用户临时目录中的 Mach-O `.test` 进程
- 要求运行时间、孤儿状态和连续异常次数同时满足
- 先发 `SIGTERM`，等待 120 秒后才可能发 `SIGKILL`
- 发信号前重新核验 PID 创建时间、UID、命令和文件路径

## 数据与状态

默认产品目录：

```text
~/.local/share/disk-guardian/               程序和 venv
~/Library/Application Support/Disk Guardian/
  ├─ disk_guard_state.json                  磁盘守护状态
  ├─ resource_guard_state.json              资源守护状态
  ├─ manual_cleanup_state.json               最近主动清理回执
  └─ disk_guard.lock                        自动/主动清理互斥锁
~/Library/Logs/Disk Guardian/               标准输出和错误日志
```

状态文件通过同目录临时文件和 `os.replace` 原子替换。清理计划只保存在
Dashboard 进程内，默认五分钟过期；执行时会重新验证候选指纹和当前进程状态。

## API

| 路径 | 方法 | 调用者 | 内容 |
|---|---|---|---|
| `/api/status` | GET | 本机面板 | 完整指标和守护状态 |
| `/api/extension/status` | GET | Chrome 扩展 | 收敛后的只读指标 |
| `/api/cleanup/latest` | GET | 本机面板 | 最近主动清理回执 |
| `/api/cleanup/scan` | POST | 同源本机面板 | 创建五分钟清理计划 |
| `/api/cleanup/execute` | POST | 同源本机面板 | 执行选中的已验证候选 |

扩展 API 不包含主动清理 token、文件路径或进程完整命令行。

## 启动与恢复

`dashboard` 使用 `KeepAlive`，意外退出后由 launchd 重启。两个 guard 使用
`StartInterval=60`，每次独立运行并退出，减少常驻权限和状态复杂度。

安装器在升级时先写入和校验 plist，再停止旧任务、加载新任务。程序目录、
状态目录和日志目录互相分离，升级不会覆盖守护状态。
