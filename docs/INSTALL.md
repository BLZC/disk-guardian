# 安装、升级与卸载

## 系统要求

- macOS，当前实现使用 `launchd` 和 `launchctl`
- Python 3.9 或更高版本
- Chrome 109 或更高版本
- 首次安装可访问 PyPI

安装器在 `~/.local/share/disk-guardian/releases/<版本-内容哈希>/venv`
创建独立 Python 环境，并固定安装 `psutil==7.2.2` 的二进制 wheel。它不
修改系统 Python 的包。

## 安装 Companion

在源码根目录运行：

```bash
./scripts/install.sh
./scripts/status.sh
```

默认配置：

| 配置 | 默认值 |
|---|---:|
| 低空间触发线 | 20 GiB |
| 清理停止线 | 30 GiB |
| 检查周期 | 60 秒 |
| 仪表盘端口 | 18765 |
| 开发版扩展 ID | `ccpomkognonnccbjmiapheoadpnepnde` |

自定义配置：

```bash
./scripts/install.sh \
  --extension-id ccpomkognonnccbjmiapheoadpnepnde \
  --threshold-gib 20 \
  --target-gib 30
```

`target-gib` 必须大于 `threshold-gib`。扩展 ID 必须是 Chrome 使用的
32 位 `a-p` 字符串。

安装器会创建：

```text
~/.local/share/disk-guardian/
~/Library/Application Support/Disk Guardian/
~/Library/Logs/Disk Guardian/
~/Library/LaunchAgents/io.github.blzc.disk-guardian.*.plist
```

三个 LaunchAgent 分别是：

```text
io.github.blzc.disk-guardian.dashboard
io.github.blzc.disk-guardian.disk-guard
io.github.blzc.disk-guardian.resource-guard
```

它们均在当前用户下运行，不要求 root。

## 安装 Chrome 扩展

开发环境：

1. 打开 `chrome://extensions`
2. 开启“开发者模式”
3. 点击“加载已解压的扩展程序”
4. 选择 `chrome-extension/`
5. 将扩展固定到工具栏

仅安装 Chrome 扩展不会启用自动清理。弹窗显示“自动清理已启用”才表示
Companion 的磁盘守护已经加载。

## 升级

在新版源码目录重新运行：

```bash
./scripts/install.sh
```

安装器会保留现有的扩展 ID 和清理阈值，在独立 staging 目录完成源码复制、
依赖安装和语法检查，成功后原子切换 `current` 链接并重新加载三个
LaunchAgent。同一内容版本会直接复用。

如果 Chrome Web Store 分配了新的扩展 ID：

```bash
./scripts/install.sh --extension-id <商店扩展ID>
```

Companion 的 CORS 白名单会更新为该 ID。旧 ID 随之失效。

## 状态检查

```bash
./scripts/status.sh
```

状态脚本检查：

- 三个 LaunchAgent 是否加载
- 当前状态、累计运行次数和最近退出码
- `http://127.0.0.1:18765/api/extension/status` 是否可访问
- 自动清理是否启用及触发/恢复阈值
- 是否存在非空错误日志

浏览器也可以直接打开：

```text
http://127.0.0.1:18765/
```

## 卸载

停止并删除后台任务和程序，保留状态与日志：

```bash
./scripts/uninstall.sh
```

同时删除磁盘守望台自己的状态和日志：

```bash
./scripts/uninstall.sh --purge-data
```

卸载脚本不会删除：

- Chrome 中已经安装的扩展
- Go 模块缓存
- 项目、仓库、worktree
- 已清理内容之外的任何用户数据

Chrome 扩展需要在 `chrome://extensions` 单独移除。

## 当前分发限制

安装器当前从 PyPI 下载 `psutil`，没有捆绑离线 wheel。若要提供完全离线
安装包，需要分别打包并测试 Apple Silicon 和 Intel macOS 的 wheel。

当前也没有 Apple Developer ID 签名和公证。面向普通用户发布前，建议提供
签名、公证的 `.pkg` 或 `.dmg`，并让安装界面明确展示自动清理白名单与卸载
入口。
