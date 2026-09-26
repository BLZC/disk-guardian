# 安全策略

## 报告问题

安全漏洞请通过 GitHub 的
[私密漏洞报告](https://github.com/BLZC/disk-guardian/security/advisories/new)
提交。普通缺陷可以使用
[GitHub Issues](https://github.com/BLZC/disk-guardian/issues)。
请不要在公开 Issue 中提交包含用户名、绝对路径、进程命令、日志或其他个人
信息的报告。

安全报告应包含：

- 受影响版本
- macOS 和 Chrome 版本
- 可复现步骤
- 预期与实际行为
- 是否涉及白名单外删除、Origin 绕过或进程误终止
- 已脱敏的最小日志

## 高优先级问题

以下问题应视为高优先级：

- 删除了安全文档白名单之外的文件
- 通过符号链接、路径竞争或扫描后替换绕过校验
- 非本机来源可以调用主动清理
- 未授权 Chrome 扩展可以读取状态
- 扩展 API 泄漏文件路径、完整命令行或清理 token
- 资源守护终止普通应用、浏览器或系统进程

## 支持范围

当前仅维护最新的 `0.2.x` 开发版本。项目尚未承诺固定的安全响应时限；收到
报告后会先确认影响范围，并在修复可用后通过 GitHub Security Advisory 和
Release 说明披露。

## 安全设计

具体白名单、失败关闭和进程身份复核见
[docs/SAFETY.md](docs/SAFETY.md)。
