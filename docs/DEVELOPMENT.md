# 本地开发与验证

## 目录

```text
server.py                    Dashboard HTTP 服务
system_metrics.py            系统、进程与 launchd 只读指标
cleanup.py                   主动清理计划与执行
cleanup_policy.py            清理白名单和安全校验唯一真值
companion/disk_guard.py      磁盘自动清理
companion/resource_guard.py  CPU/内存资源守护
dist/                        完整本机面板
chrome-extension/            Manifest V3 扩展
scripts/                     安装、状态和卸载
tests/                       回归测试
```

## 本地运行

创建环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

启动 Dashboard：

```bash
DISK_GUARDIAN_PORT=18765 .venv/bin/python server.py
```

只读检查磁盘守护：

```bash
.venv/bin/python companion/disk_guard.py --status
```

只读检查资源守护：

```bash
.venv/bin/python companion/resource_guard.py --status
```

`--status` 不删除文件或发送进程信号。

## 静态检查

```bash
bash -n scripts/install.sh scripts/status.sh scripts/uninstall.sh
python3 -m py_compile server.py system_metrics.py cleanup.py cleanup_policy.py companion/*.py
python3 -m json.tool chrome-extension/manifest.json >/dev/null
node --check chrome-extension/popup.js
node --check chrome-extension/service-worker.js
node --check dist/app.js
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```

涉及安装器时，在隔离的 HOME、安装目录、状态目录、日志目录和 LaunchAgent
目录中使用 `--no-load` 验证生成结果。不要让测试扫描或删除真实缓存。

发布前还应运行：

```bash
ruff check . --exclude dist --exclude chrome-extension
bandit -q -r . -x tests,.github
```

测试至少覆盖：

- 扩展 API 是否明确返回自动清理 ON/OFF
- API 不泄漏路径、清理 token 或完整命令行
- 安装器生成的标签、阈值、Origin 和 venv 路径
- 重复安装是否保留已有配置
- 卸载是否只删除产品自己的文件
- 主动清理计划过期、候选变化、跨站请求和共享锁

## Chrome 扩展验证

1. 启动 Companion
2. 在 `chrome://extensions` 加载 `chrome-extension/`
3. 确认扩展 ID 与安装器配置一致
4. 打开弹窗，确认自动清理显示 ON
5. 停止 dashboard，确认徽标变为红色 `!`
6. 恢复 dashboard，确认一分钟内恢复或手动刷新
7. 检查扩展 service worker 和弹窗控制台没有错误

## 安全 Review

修改清理逻辑时，从候选原始路径一路检查到删除调用：

```text
目录枚举
  → 名称与类型
  → realpath 与 owner
  → 年龄与文件结构
  → 活跃进程与 lsof
  → 执行前二次验证
  → 精确 unlink/rmtree
  → df 与状态回读
```

任何新清理类别都必须有独立的可重建证据和失败关闭测试。不要通过宽泛 glob、
用户可输入路径或递归清理目录根来实现。

## 版本

发布新扩展时同步更新：

- `chrome-extension/manifest.json`
- `CHANGELOG.md`
- ZIP 文件名与 SHA-256
- Companion 的 `install.json` 版本
- 商店披露和截图（如果行为或权限变化）
