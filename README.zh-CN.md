# Codex Session Renamer

[English](./README.md) | [简体中文](./README.zh-CN.md)

> 当前版本：v0.6.2

这是一个用于查看、重命名和清理 Codex 会话的本地 Web 工具。界面使用中文，适合管理分布在多个项目目录中的大量会话。

## 功能

### 会话发现与查看

- 同时读取旧版 `~/.codex/session_index.jsonl` 索引和当前的 `~/.codex/state_5.sqlite` 数据库。
- 匹配 `~/.codex/sessions/**` 下的活动日志和 `~/.codex/archived_sessions/` 下的归档日志。
- 按工作目录分组，并按照最近更新时间由近到远排序。
- 在列表中直接显示会话标题、更新时间、ID、消息数量、内容预览和推荐标题。
- 支持进入详情页查看会话中的用户和助手消息。
- 支持根据当前标题、内容预览和完整会话内容搜索。
- 支持筛选尚未使用有效标题的会话，以及改名后内容又发生变化的会话。

### 标题推荐与改名

- 生成三级标题：当前目录、整体任务和最近两轮状态。
- 通过 DashScope 兼容接口调用 `qwen3.5-flash`，并关闭思考模式以降低标题生成成本。
- 分别推理整体任务和最近两轮状态，再由 Qwen 审校最近状态草稿，去除路径和低价值表述。
- 整体任务的模型输入上限采用保守的 100,000 token 预算。
- 构建标题上下文时忽略第一条用户环境或系统记录。
- 仅在点击 **一键标题推荐** 或 **单会话标题推荐** 时调用模型，普通页面刷新不会触发模型。
- 推荐标题会填入改名输入框，但不会自动应用。
- 标题推荐和会话改名相互独立，生成推荐不会改变会话数量或当前标题。
- 支持在列表中手动改名单个会话，也支持对当前筛选结果批量改名。
- 对当前会话使用 Codex `thread/name/set` app-server 方法，使标题在继续对话后仍能保持。

### 变化跟踪与清理

- 当会话内容与上次成功改名时的内容不同时，显示“会话变化”状态。
- 生成推荐后仍保留变化状态，只有成功改名后才清除。
- 删除会话时同步处理索引或数据库，并将日志移动到 `~/.codex/session-renamer-trash/` 以便恢复。
- 修改旧索引或当前数据库前创建带时间戳的备份。
- 推荐、改名、批量改名和删除成功后显示临时操作提示。

### 性能与隐私

- 只有在明确配置并触发 Qwen 标题推荐时，才会将清理后的会话上下文发送给模型服务商。
- 缓存推荐标题和日志元数据，避免重复解析未变化的会话文件。
- 仅在详情页、内容搜索、变化筛选和标题生成时加载完整会话内容。
- 所有会话管理页面和操作都要求访问 Token。
- 返回 `Cache-Control: no-store`，减少浏览器缓存私人会话内容。

## 环境要求

- Python 3.10 或更高版本
- 支持 `app-server` 的 Codex 安装，用于持久化改名
- 能够访问 Codex 数据目录，默认是 `~/.codex`

## 安装

```bash
git clone https://github.com/zhangyanbo2007/codex-session-renamer.git
cd codex-session-renamer
python3 -m venv .venv
.venv/bin/pip install -e .
```

生成强随机访问 Token 并启动本地服务：

```bash
export SESSION_RENAMER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
bash run.sh
```

打开：

```text
http://127.0.0.1:8891/?token=<SESSION_RENAMER_TOKEN>
```

启动脚本会依次使用环境变量 `PYTHON`、`.venv/bin/python` 和 `PATH` 中的 `python3`。

## 使用方法

使用标题推荐前配置 Qwen：

```bash
export SESSION_RENAMER_DASHSCOPE_API_KEY='your-dashscope-api-key'
export SESSION_RENAMER_QWEN_MODEL='qwen3.5-flash'
export SESSION_RENAMER_TOKEN='your-strong-access-token'
bash run.sh
```

打开 Web 界面后：

1. 使用目录下拉框或搜索框缩小会话范围。搜索会匹配当前标题、内容预览和会话内容。
2. 点击 **一键标题推荐**，为当前页面筛选出的会话重新生成推荐。该操作不会改名，也不会改变会话数量。
3. 点击 **单会话标题推荐**，只刷新一个会话的推荐，并将结果填入对应的改名输入框。
4. 检查或编辑输入框内容，然后点击 **单会话改名** 应用标题。
5. 点击 **一键全部改名**，将推荐标题应用到当前筛选范围内的会话。
6. 点击会话标题进入详情页，可以查看消息、重新推荐标题、改名或删除会话。
7. 使用 **只看未改名** 筛选没有三级标题的会话；使用会话变化筛选查看上次改名后内容又发生变化的会话。
8. 删除前先检查会话内容。删除的日志会移入 `~/.codex/session-renamer-trash/`，同时会先备份索引或数据库。

标题格式为 `当前目录 | 整体任务 | 最近两轮状态`。刷新页面不会调用 Qwen，只有明确点击标题推荐按钮才会重新生成推荐。

## 配置

可以复制 `.env.example` 作为参考，但应通过进程环境变量提供密钥，或将密钥保存在不会提交的受保护本地文件中。

| 变量 | 是否必需 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `SESSION_RENAMER_TOKEN` | 是 | 无 | 所有私人页面和操作的访问 Token |
| `CODEX_HOME` | 否 | `~/.codex` | Codex 数据目录 |
| `SESSION_RENAMER_INDEX_PATH` | 否 | `$CODEX_HOME/session_index.jsonl` | 旧版索引路径覆盖 |
| `SESSION_RENAMER_HOST` | 否 | `127.0.0.1` | 本地监听地址 |
| `SESSION_RENAMER_PORT` | 否 | `8891` | 本地 HTTP 端口 |
| `SESSION_RENAMER_CODEX_BIN` | 否 | 自动检测 | 支持 app-server 的 Codex 可执行文件 |
| `SESSION_RENAMER_TITLE_PROVIDER` | 否 | `qwen` | 使用 `local` 时不调用模型，仅保留现有标题 |
| `SESSION_RENAMER_DASHSCOPE_API_KEY` | 使用 Qwen 时必需 | 无 | DashScope API Key |
| `SESSION_RENAMER_QWEN_MODEL` | 否 | `qwen3.5-flash` | 标题生成模型 |
| `SESSION_RENAMER_QWEN_BASE_URL` | 否 | DashScope 兼容接口 | 自定义 API 地址 |
| `SESSION_RENAMER_QWEN_TIMEOUT` | 否 | `8` | 模型请求超时时间，单位为秒 |
| `SESSION_RENAMER_QWEN_PROXY` | 否 | 自动检测本地代理或不使用 | 模型请求使用的 HTTP(S) 代理 |
| `SESSION_RENAMER_TITLE_WORKERS` | 否 | `6` | 并发标题请求的最大数量 |

标题语义只由 Qwen 生成。没有 API Key 时，程序保留现有标题，不使用本地规则生成推荐。

## 可选 FRP 公网访问

本地使用不需要 FRP。仓库中的 `frp-tunnel.sh` 是通用辅助脚本，会从被忽略的 `.env.local` 读取可选的机器配置。

必需的 FRP 配置：

```bash
export SESSION_RENAMER_FRP_CONFIG=/path/to/frpc.toml
export SESSION_RENAMER_PUBLIC_HOST=example.com
export SESSION_RENAMER_TOKEN='use-a-long-random-value'
bash frp-tunnel.sh start
```

其他变量包括 `SESSION_RENAMER_FRP_BIN`、`SESSION_RENAMER_FRP_ADMIN`、`SESSION_RENAMER_FRP_PROXY_NAME`、`SESSION_RENAMER_REMOTE_PORT`、`SESSION_RENAMER_FRP_MANAGE_CONFIG`、`SESSION_RENAMER_LOG_FILE` 和 `SESSION_RENAMER_PID_FILE`。

只验证配置，不启动服务：

```bash
bash frp-tunnel.sh validate
```

启动、检查或停止本地服务；停止操作不会关闭共享的 FRP 客户端：

```bash
bash frp-tunnel.sh start
bash frp-tunnel.sh status
bash frp-tunnel.sh stop
```

> FRP TCP 转发不提供 TLS。Codex 会话可能包含源代码、凭据、个人信息和系统上下文。优先使用可信的私有网络。公网访问时，应在服务前增加 TLS 和更强的身份认证。不要在缺少强 Token 的情况下公开服务。

## 安全说明

- 首次使用前备份 `~/.codex`。
- 批量改名前先检查推荐标题。
- 删除操作会修改 Codex 索引并将日志移动到本地回收目录；操作前确认当前目录和搜索筛选范围。
- 查询参数中的 Token 可能出现在浏览器历史和中间日志中；请使用私有网络，Token 可能泄露时应及时轮换。
- 只有点击标题推荐按钮后，程序才会将清理后的会话上下文发送给配置的模型服务商。

## 开发

运行完整测试：

```bash
python3 -m unittest discover -s tests -v
```

检查 Shell 脚本和空白格式：

```bash
bash -n run.sh frp-tunnel.sh
git diff --check
```

版本历史见 [CHANGELOG.md](./CHANGELOG.md)。

## 许可证

MIT
