# Chrome Web Store 上架准备

## 产品定位

推荐名称：

```text
磁盘守望台 - macOS 本机资源监控
```

单一用途：

> 连接用户自行安装的 macOS 本机 Companion，在 Chrome 工具栏中展示磁盘、
> CPU、内存、Swap 和白名单自动清理状态，并提供本机完整面板入口。

短描述：

> 查看 Mac 磁盘与系统资源状态，确认本机白名单自动清理是否正常运行。

长描述：

> 磁盘守望台连接运行在 127.0.0.1 的 macOS Companion，展示磁盘剩余空间、
> CPU、内存、Swap、进程排行和自动清理状态。磁盘剩余空间低于用户配置的
> 阈值时，Companion 只会处理经过路径、所有者、文件类型、年龄、打开文件
> 和活跃进程校验的可重建开发产物。扩展本身不具备 macOS 文件删除权限，
> 不读取浏览历史、网页内容、Cookie、账号或下载记录，也不向互联网发送
> 监控数据。

## 权限说明

| 权限 | 用途 |
|---|---|
| `alarms` | 每分钟刷新一次本机状态和工具栏徽标 |
| `storage` | 本地保存最后一次状态和连接错误，Companion 暂时离线时提供提示 |
| `http://127.0.0.1:18765/*` | 访问用户本机安装的 Companion |

扩展不申请：浏览历史、标签页读取、网页内容、Cookie、下载、文件系统或
Native Messaging。

## 自动清理披露

商店页面和隐私政策都应明确：

1. Chrome 扩展本身不能删除 macOS 文件
2. 用户必须单独安装本机 Companion
3. 自动清理由当前用户权限下的 Companion 执行
4. 默认低于 20 GiB 触发，恢复到 30 GiB 停止
5. 删除范围是固定白名单，具体见安全文档
6. 用户可以通过卸载 Companion 完全停用自动清理

不要把“安装扩展”等同于“已经启用自动清理”。

## 扩展 ID

开发版通过 manifest 的 `key` 固定为：

```text
ccpomkognonnccbjmiapheoadpnepnde
```

首次上传商店时使用 `scripts/package_chrome_store.py` 生成的专用 ZIP。
这个包会移除开发版自签 `key`，由 Chrome Web Store 分配正式 Item ID。
获得商店 ID 后必须让用户使用它安装或升级 Companion：

```bash
./scripts/install.sh --extension-id <商店扩展ID>
```

否则 Companion 不会向商店版扩展返回跨域数据。上传后从 Package 页面复制
商店 Public key，再更新源码 `manifest.json` 的 `key`，使后续开发版与商店
版本使用相同 ID。

当前商店 Item ID：

```text
knfhjpciofoakljbmneaaailglnmamlk
```

## 上架素材

准备以下素材：

- 128×128 扩展图标
- 至少 1 张 1280×800 或 640×400 截图
- 推荐 3 张截图：弹窗、完整面板、自动清理安全边界
- 440×280 小型宣传图
- 可选 1400×560 大型宣传图
- 可公开访问的隐私政策 URL
- Companion 安装与卸载文档 URL

截图不要包含用户名、绝对文件路径、PID、命令行、公司标识或内部服务信息。

## 打包

ZIP 根目录必须直接包含 `manifest.json`。首次商店上传使用：

```bash
python3 scripts/package_chrome_store.py
shasum -a 256 -c disk-guard-chrome-store-0.2.1.zip.sha256
```

商店包不含开发版 `key`。提交前解压到空目录并通过
`chrome://extensions` 真实加载。

## 开发者后台流程

1. 注册 Chrome Web Store 开发者账号并完成一次性费用
2. 创建新项目并上传扩展 ZIP
3. 填写商店描述、单一用途、权限理由和隐私实践
4. 上传截图和宣传图
5. 提供隐私政策与 Companion 安装页
6. 选择发布地区和可见性
7. 提交审核
8. 获得正式扩展 ID 后更新 Companion 安装说明并重新验证

## 发布前阻塞项

当前还需要：

- 生成不含本机数据的商店截图
- 提供签名、公证的 Companion 安装包
- 完成 Intel macOS 验证
- 完成全新用户安装、升级、卸载和回滚验证
- 用商店正式 ID 验证 CORS

当前开发版可以本机使用，但这些事项完成前不建议面向普通消费者公开上架。
