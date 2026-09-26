# Chrome Web Store Listing

## 基本信息

- 名称：`磁盘守望台 - macOS 本机资源监控`
- 默认语言：`简体中文`
- 类别：`生产力工具`
- 可见性：`公开`
- 地区：`所有地区`
- 成熟内容：`否`

## 简短说明

```text
查看 Mac 磁盘、CPU、内存与 Swap，并确认本机白名单自动清理是否正常运行。
```

## 详细说明

```text
磁盘守望台连接运行在 127.0.0.1 的 macOS Companion，在 Chrome 工具栏中展示磁盘剩余空间、CPU、内存、Swap、进程排行和自动清理状态。

主要能力：
• 每分钟更新工具栏状态和低空间提醒
• 弹窗查看磁盘、CPU、内存与 Swap
• 打开完整本机监控面板
• 显示自动清理是否启用、触发阈值和最近结果
• 展示高占用进程，但普通应用和系统进程不会被自动终止

自动清理说明：
Chrome 扩展自身不能删除 macOS 文件。用户必须单独安装开源的本机 Companion。默认情况下，磁盘剩余空间低于 20 GiB 时，Companion 会检查可重建开发产物；恢复到 30 GiB 后停止。每个候选都必须通过路径、所有者、文件类型、年龄、打开文件和活跃进程校验。

始终保留：
• Go 模块缓存
• 项目、Git 仓库和 worktree
• 文档、照片、下载和桌面文件
• 浏览器和其他应用数据
• 无法证明可重建的文件

隐私：
扩展只连接 http://127.0.0.1:18765/，不读取网页内容、浏览历史、Cookie、账号信息或下载记录，也不向互联网发送监控数据。

安装 Companion 和完整安全说明：
https://github.com/BLZC/disk-guardian
```

## 单一用途

```text
连接用户自行安装的 macOS 本机 Companion，在 Chrome 工具栏中展示磁盘和系统资源状态、自动清理状态，并提供本机监控面板入口。
```

## 权限说明

### alarms

```text
每分钟读取一次本机 Companion 的只读状态，用于更新工具栏徽标和低磁盘空间提醒。
```

### storage

```text
仅在 chrome.storage.local 中保存最后一次只读状态、更新时间和连接错误，以便 Companion 暂时离线时显示明确提示。
```

### http://127.0.0.1:18765/*

```text
访问用户本机安装的 Companion。扩展只调用 /api/extension/status 只读接口；完整监控数据和清理写接口不会向扩展开放。
```

### 远程代码

```text
否。扩展不下载或执行远程 JavaScript、WebAssembly 或其他代码。
```

## 数据使用声明

- 收集用户数据：`否`
- 出售用户数据：`否`
- 将用户数据用于与单一用途无关的目的：`否`
- 将用户数据用于信用或借贷：`否`
- 传输数据到第三方：`否`
- 本机系统指标仅在用户设备上处理

## URLs

- 隐私政策：<https://blzc.github.io/disk-guardian/PRIVACY.html>
- 主页：<https://github.com/BLZC/disk-guardian>
- 支持：<https://github.com/BLZC/disk-guardian/issues>
- Companion 安装说明：<https://blzc.github.io/disk-guardian/docs/INSTALL.html>
- 安全说明：<https://blzc.github.io/disk-guardian/docs/SAFETY.html>

## 测试说明

```text
1. 安装 Companion：
   git clone https://github.com/BLZC/disk-guardian.git
   cd disk-guardian
   ./scripts/install.sh --extension-id <当前商店 Item ID>

2. 确认 http://127.0.0.1:18765/ 可以打开。
3. 点击扩展图标，弹窗应显示“已连接”和“自动清理已启用”。
4. 点击“打开完整面板”，应打开本机 Dashboard。

无需测试账号。扩展不访问外部账号或云端服务。
```

## 素材

- 商店图标：`chrome-extension/icons/icon128.png`
- 截图 1：`store-assets/screenshots/dashboard-overview-1280x800.png`
- 截图 2：`store-assets/screenshots/safety-cleanup-1280x800.png`
- 小型宣传图：`store-assets/promo/small-promo-440x280.png`

## 首次上传后检查

1. 打开 Package 标签页并记录 Item ID。
2. 从 Package 页复制商店 Public key，更新 `manifest.json` 的 `key`。
3. 升级扩展版本号并重新打包后续版本。
4. 使用商店 Item ID 重新安装 Companion：

```bash
./scripts/install.sh --extension-id <商店 Item ID>
```
