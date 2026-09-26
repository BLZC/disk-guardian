# 磁盘守望台 Chrome 插件

这是磁盘守望台的 Chrome 界面。插件只负责实时展示和入口，本机
Companion 服务负责读取 macOS 的磁盘、CPU、内存、Swap 和守护状态。

## 安装

1. 确认本机页面可以打开：<http://127.0.0.1:18765/>
2. 打开 `chrome://extensions`
3. 打开右上角「开发者模式」
4. 点击「加载已解压的扩展程序」
5. 选择本目录 `chrome-extension`
6. 建议将「磁盘守望台」固定到 Chrome 工具栏

插件固定 ID：

```text
ccpomkognonnccbjmiapheoadpnepnde
```

## 能力

- 弹窗实时展示磁盘、CPU、内存、Swap
- 展示磁盘守护与资源守护状态
- 明确显示自动清理 ON/OFF、触发线和恢复线
- 展示 CPU 占用最高的 3 个进程
- 每分钟更新工具栏徽标
- 点击打开完整本机监控面板

徽标规则：

- 无徽标：剩余空间不低于 20 GiB
- 黄色数字：剩余空间低于 20 GiB
- 红色数字：剩余空间低于 10 GiB
- 红色 `!`：本机 Companion 未连接或自动清理未启用

## 权限

插件仅申请：

- `alarms`：每分钟刷新状态
- `storage`：保存最后一次只读状态
- `http://127.0.0.1:18765/*`：访问本机 Companion

插件不申请浏览记录、标签页读取、文件系统、下载、Cookie 或网站内容权限。
主动文件清理仍需在完整面板中扫描并二次确认。

## 依赖

插件需要本机 Companion 持续运行：

```text
io.github.blzc.disk-guardian.dashboard
io.github.blzc.disk-guardian.disk-guard
io.github.blzc.disk-guardian.resource-guard
```

如果弹窗显示「本机服务未连接」，先检查
<http://127.0.0.1:18765/> 是否可以访问。

## 卸载

从 `chrome://extensions` 中移除插件即可。移除插件不会删除本机 Companion
或其配置。
