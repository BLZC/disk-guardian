# 故障排查

先运行：

```bash
./scripts/status.sh
```

它会同时检查 LaunchAgent、Companion API 和错误日志。

## 插件显示“本机服务未连接”

1. 打开 <http://127.0.0.1:18765/>
2. 运行 `./scripts/status.sh`
3. 确认 `dashboard` 显示 `loaded=yes`
4. 查看 `~/Library/Logs/Disk Guardian/dashboard.err.log`

若使用 Chrome Web Store 版本，确认安装器配置的是实际商店 ID：

```bash
./scripts/install.sh --extension-id <商店扩展ID>
```

扩展 Origin 不在 Companion 白名单时，浏览器会拦截响应。

## 自动清理显示 OFF

`/api/extension/status` 中以下字段决定插件显示：
```json
{
  "automatic_cleanup": {
    "enabled": true,
    "healthy": true
  }
}
```

如果为 `false`：
1. 重新运行 `./scripts/install.sh`
2. 运行 `./scripts/status.sh`
3. 检查 `disk-guard` 是否 `loaded=yes`
4. 查看 `disk-guard.err.log`

## 空间低于 10 GiB 但没有删除

这通常意味着没有通过白名单的安全候选。检查
`disk_guard_state.json` 的 `last_event.actions`：

```text
~/Library/Application Support/Disk Guardian/disk_guard_state.json
```

常见跳过原因：

- `active_build` / `build_started`：存在 Go 构建或测试
- `process_check_failed`：无法可靠读取进程
- `open_file_check_failed`：无法可靠读取打开文件
- `cache_not_quiet`：共享构建缓存最近仍在变化
- `active_or_open`：具体子项正在使用
- `root_safety`：缓存根路径或所有者不符合不变量

守护不会为达到 20 GiB 擅自删除白名单外内容。

## 首次安装时 psutil 失败

安装器需要从 PyPI 获取固定版本：

```text
psutil==7.2.2
```

确认网络和 Python venv 可用，然后重新运行安装器。安装过程是幂等的，已写入
的 plist 在依赖安装成功前不会被加载。

## 端口 18765 被占用

查找占用者：

```bash
lsof -nP -iTCP:18765 -sTCP:LISTEN
```

当前扩展和 Companion 固定使用 18765。先停止占用该端口的旧版 Companion
或其他本机程序，再重新运行安装器。源码开发者若要更换端口，需要同步修改
Companion、扩展脚本和 `manifest.json` 并重新加载扩展。

## 日志

```text
~/Library/Logs/Disk Guardian/dashboard.log
~/Library/Logs/Disk Guardian/dashboard.err.log
~/Library/Logs/Disk Guardian/disk-guard.log
~/Library/Logs/Disk Guardian/disk-guard.err.log
~/Library/Logs/Disk Guardian/resource-guard.log
~/Library/Logs/Disk Guardian/resource-guard.err.log
```

正常的定时检查不一定每分钟写日志。守护只在详细模式、动作或错误时输出。

## 完全重装

```bash
./scripts/uninstall.sh --purge-data
./scripts/install.sh
./scripts/status.sh
```

这只删除磁盘守望台自己的程序、状态和日志，不会清理 Go 缓存或个人文件。
