# 版本记录

## 0.2.1 - 2026-09-26

### 变更

- 磁盘自动清理触发线从 10 GiB 提升至 20 GiB
- 为保留滞回，清理停止线从 20 GiB 提升至 30 GiB
- 同步更新 Chrome 扩展、Dashboard、安装器、商店文案和测试

## 0.2.0 - 2026-09-26

### 新增

- 可分发的 macOS Companion 安装、状态和卸载脚本
- 内容哈希版本目录、原子 `current` 切换和独立 Python venv
- 固定 `psutil==7.2.2` 二进制 wheel 与第三方许可证声明
- GitHub Actions macOS 回归与静态语法检查
- 清理策略、安装器、API 边界、扩展权限和资源守护回归测试
- 中立的 `io.github.blzc.disk-guardian.*` LaunchAgent 标签
- Chrome 扩展中的自动清理 ON/OFF、触发线和恢复线
- Companion 扩展 API v2 的自动清理状态
- 安装、架构、安全、排障、上架、开发、隐私和安全政策文档

### 变更

- Chrome 扩展版本提升至 0.2.0
- 产品状态迁移到 `~/Library/Application Support/Disk Guardian`
- 日志迁移到 `~/Library/Logs/Disk Guardian`
- 重复安装保留已有扩展 ID 和清理阈值
- `server.py` 只负责 HTTP/API，系统指标拆入 `system_metrics.py`
- 自动与主动清理共用 `cleanup_policy.py` 中的一份白名单与安全规则

### 安全

- Go 缓存和临时树递归校验所有权、年龄、结构、Git 数据和符号链接
- 安装器先完成依赖、编译和守护预检，健康后再提交版本；失败恢复旧任务
- 产品目录使用标记、真实路径和互不嵌套门禁，卸载遇到异常路径会拒绝
- `psutil` 使用官方 wheel SHA-256 哈希锁定，OSV 查询未发现已知漏洞
- 扩展 Origin 只能读取收敛 API；完整 API 和清理 POST 返回 403
- Chrome 扩展仍不拥有文件删除接口
- 扩展 API 继续隐藏清理 token、路径和进程完整命令行

## 0.1.0 - 2026-09-25

- 磁盘、CPU、内存和 Swap 实时监控
- 10/20 GiB 低空间自动清理
- 保守型临时测试进程治理
- 两阶段主动清理
- Manifest V3 Chrome 扩展 MVP
