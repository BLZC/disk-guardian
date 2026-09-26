# 隐私说明

最后更新：2026-09-26

## 数据处理

磁盘守望台在用户自己的 Mac 上处理以下数据：

- 磁盘总容量、已用和可用容量
- CPU、内存、Swap 和 Load
- 进程 PID、名称、CPU、内存、运行时间和所有者是否为当前用户
- 本机守护进程状态、检查时间和动作结果
- 主动清理候选的本机路径，仅在完整本机面板中展示

这些数据用于本机监控、安全校验和清理回执。

## 数据传输

Chrome 扩展只访问：

```text
http://127.0.0.1:18765/
```

监控数据不会由本项目发送到互联网。扩展不会接入分析、广告或遥测服务。
首次安装 Companion 时，`pip` 会访问 Python 包源下载 `psutil==7.2.2`
二进制 wheel；该网络请求由安装器完成，不包含监控数据。

## Chrome 本地存储

扩展在 `chrome.storage.local` 保存：

- 最后一次只读状态
- 状态更新时间
- 最近一次连接错误

移除扩展后由 Chrome 按其扩展数据规则处理这些数据。

## 不读取的内容

扩展不读取或收集：

- 浏览历史
- 网页内容和表单
- Cookie
- Chrome 账号信息
- 下载记录
- 书签
- 键盘输入
- 用户文档、照片或消息

## 本机状态与日志

Companion 默认将状态写入：

```text
~/Library/Application Support/Disk Guardian/
```

日志写入：

```text
~/Library/Logs/Disk Guardian/
```

`./scripts/uninstall.sh --purge-data` 可以删除这些产品数据。

## 自动清理

自动清理由本机 Companion 执行。扩展本身没有 macOS 文件系统权限。清理只
针对安全文档列出的可重建产物，并在删除前检查路径、所有者、文件类型、年龄、
打开文件和活跃进程。

扩展 API 不返回清理 token、候选文件路径或进程完整命令行。

## 联系

隐私问题请通过
[GitHub Issues](https://github.com/BLZC/disk-guardian/issues) 提交；如果问题
包含本机路径、日志、进程信息或其他敏感数据，请改用
[私密漏洞报告](https://github.com/BLZC/disk-guardian/security/advisories/new)。
