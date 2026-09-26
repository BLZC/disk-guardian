# 磁盘守望台（Disk Guardian）

磁盘守望台是一套面向 macOS 的本机资源监控与保守型自动清理工具。它由
Chrome 扩展、本机 Companion 和三个 LaunchAgent 组成：

```text
Chrome 扩展
  ├─ 查看磁盘、CPU、内存、Swap 和自动清理状态
  └─ 打开本机完整面板
        ↓ http://127.0.0.1:18765
本机 Companion
  ├─ dashboard       实时监控和主动清理界面
  ├─ disk-guard      低磁盘空间时执行白名单自动清理
  └─ resource-guard  保守处理异常的临时测试进程
```

Chrome 扩展没有 macOS 文件系统权限。真正的自动清理由安装在用户账户下的
Companion 执行。因此，只安装扩展无法获得自动清理能力。

## 当前能力

- 每 3 秒刷新完整面板，每分钟刷新 Chrome 工具栏徽标
- 展示磁盘、CPU、内存、Swap、系统 Load 和进程排行
- 剩余空间低于 `20 GiB` 时自动触发磁盘清理
- 可用空间恢复到 `30 GiB` 后停止清理
- 主动清理使用“扫描 → 选择 → 二次确认 → 执行”流程
- 自动保护活跃 Go 构建、打开文件、符号链接和 Git 数据
- 资源守护只处理当前用户临时目录中的异常 Mach-O `.test` 进程
- 所有服务仅监听 `127.0.0.1`

阈值可在安装时调整。清理范围是固定白名单，不会为达到目标容量而扩展到
下载、文档、照片、工作区、Git 仓库、浏览器数据或应用数据。

## 快速开始

要求：

- macOS
- Python 3.9 或更高版本
- 首次安装时可访问 PyPI，用于安装 `psutil==7.2.2` 二进制 wheel
- Chrome 109 或更高版本

安装或升级 Companion：

```bash
git clone https://github.com/BLZC/disk-guardian.git
cd disk-guardian
./scripts/install.sh
./scripts/status.sh
```

打开 <http://127.0.0.1:18765/>。随后在 `chrome://extensions` 中开启开发者
模式，点击“加载已解压的扩展程序”，选择 `chrome-extension/`。

开发版扩展 ID 固定为：

```text
ccpomkognonnccbjmiapheoadpnepnde
```

Chrome Web Store 上架后扩展 ID 可能变化。使用商店版 ID 重新运行安装器：

```bash
./scripts/install.sh --extension-id <32位商店扩展ID>
```

安装器会在独立目录完成依赖和语法检查，成功后原子切换 `current` 链接，
保留现有阈值和扩展 ID，并重新加载后台服务。

## 自动清理做什么

磁盘守护每 60 秒检查一次。进入压力态后，按以下顺序处理：

1. `/private/tmp` 下超过 100 MiB、至少一小时未修改、无人使用的 Mach-O
   `.test` 文件
2. `/private/tmp` 下名称和结构均符合白名单的独立 Go 构建缓存
3. 当前用户临时目录下至少一小时未修改、无人使用的 `go-build*` 和
   `go-link*` 目录
4. `~/.cache/codex-go-build` 中经过二次活跃检查的可重建内容

每个候选都要通过路径、所有者、真实路径、类型、年龄、进程引用和打开文件
检查。共享 Go 构建缓存清理前还会连续检查活跃构建。任一检查失败就跳过。

以下内容始终保留：

- `~/.cache/codex-go-mod` 模块缓存
- 项目、Git 仓库和 worktree
- 文档、照片、下载和桌面文件
- 浏览器、Codex、飞书和其他应用数据
- 无法证明可重建的文件

完整门禁见 [安全设计](docs/SAFETY.md)。

## 常用命令

自定义阈值：

```bash
./scripts/install.sh --threshold-gib 20 --target-gib 30
```

检查服务、API 和错误日志：

```bash
./scripts/status.sh
```

卸载程序并保留状态与日志：

```bash
./scripts/uninstall.sh
```

同时删除磁盘守望台自己的状态与日志：

```bash
./scripts/uninstall.sh --purge-data
```

卸载不会删除 Chrome 扩展、项目、Go 模块缓存或个人文件。

## 文档

- [安装与升级](docs/INSTALL.md)
- [系统架构](docs/ARCHITECTURE.md)
- [清理与资源治理安全边界](docs/SAFETY.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [Chrome Web Store 上架准备](docs/CHROME_WEB_STORE.md)
- [本地开发与验证](docs/DEVELOPMENT.md)
- [隐私说明](PRIVACY.md)
- [安全策略](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)
- [版本记录](CHANGELOG.md)
- [第三方依赖声明](THIRD_PARTY_NOTICES.md)

## 当前发布状态

源码、Companion、开发版扩展和完整本机链路已在 Apple Silicon Mac 上验证，
源码发布在 [GitHub](https://github.com/BLZC/disk-guardian)，Chrome 扩展尚未
提交 Chrome Web Store。当前安装器是用户级 shell 安装器，尚未经过 Apple
Developer ID 签名和公证，因此不是面向普通消费者的一键 `.pkg` 或 `.dmg`
安装体验。Intel macOS 仍需独立运行验收。
