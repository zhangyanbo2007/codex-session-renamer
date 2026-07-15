# Codex Session Renamer

[English](./README.md) | [简体中文](./README.zh-CN.md)

> 当前版本：v0.8.0

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
- 存在最近上下文时，一次成功推荐会调用 Qwen 四次：生成整体任务、进行一次结构化的整体质量审校/纠正、生成最近状态、审校最近状态。整体审校拒绝候选时，会在该次审校后停止。
- 将路径、文件名、截图和文件视为证据载体，而不是足以单独成立的任务对象。无效或不可接受的结果不会生成推荐。
- 纳入最近的助手证据，并为合并后的整体证据使用保守的 100,000 字符输入包络。实现会预留提示词开销，将最近证据限制为 20,000 字符，并在长会话中兼顾原始任务和最新意图；这不是基于精确分词器的 100,000 Token 上限。
- 构建标题上下文时忽略第一条用户环境或系统记录。
- 当会话变化后明确刷新推荐时，由模型生成的整体任务段可以随任务演变；人工编写的整体任务段始终受保护，只更新最近状态段。
- 列表页和详情页的被动刷新绝不调用 Qwen；只有明确的标题推荐、自动改名或标题建议 API 操作才可能调用模型。
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

- 只有明确执行标题推荐或自动改名操作，或发起经过认证的标题建议 API 请求时，才会将清理后的会话上下文发送给配置的模型服务商。列表页和详情页的被动刷新不会发送这些内容。
- 缓存推荐标题和日志元数据，避免重复解析未变化的会话文件。
- 仅在详情页、内容搜索、变化筛选和标题生成时加载完整会话内容。
- 可选为所有会话管理页面和操作启用应用访问 Token。
- 默认只监听本机回环地址；无 Token 模式仅用于本机访问，或已由带认证的 HTTPS 反向代理完整保护的部署。
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

启动仅供本机访问的服务：

```bash
bash run.sh
```

打开：

```text
http://127.0.0.1:8891/
```

如需启用应用层认证，请先生成强随机访问 Token：

```bash
export SESSION_RENAMER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
bash run.sh
```

然后打开：

```text
http://127.0.0.1:8891/?token=<SESSION_RENAMER_TOKEN>
```

启动脚本会依次使用环境变量 `PYTHON`、`.venv/bin/python` 和 `PATH` 中的 `python3`。

## 操作流程

> 以下截图中的会话、目录、标题、消息、ID 和时间均为虚构演示数据，不包含任何真实 Codex 对话内容。

### 1. 浏览、筛选和搜索会话

可以选择工作目录，也可以根据标题和会话内容搜索。列表页直接提供推荐、改名和删除操作，不需要先进入详情页。

![按目录筛选会话](./docs/images/workflow-01-session-list.png)

### 2. 一键生成标题推荐

点击 **一键标题推荐**，为当前筛选结果刷新推荐标题。该操作只更新推荐标题和改名输入框，不会直接改名。

![为当前会话列表生成标题推荐](./docs/images/workflow-02-title-recommendations.png)

### 3. 为单个会话生成推荐

通过搜索定位会话后，点击 **单会话标题推荐**。生成的三级标题会填入该会话的改名输入框，便于检查和编辑。

![为单个会话生成标题推荐](./docs/images/workflow-03-single-session-recommendation.png)

### 4. 应用确认后的标题

根据需要编辑输入框，再点击 **单会话改名**。操作成功后，页面会显示临时提示，并展示改名后的标题。

![单会话改名成功提示](./docs/images/workflow-04-renamed-status.png)

### 5. 查看会话内容后再清理

点击会话标题进入详情页，可以查看消息、重新生成推荐、保存新标题，或在确认内容无价值后删除会话。

![会话详情与内容检查](./docs/images/workflow-05-session-detail.png)

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

标题格式为 `当前目录 | 整体任务 | 最近两轮状态`。列表页和详情页的被动刷新不会调用 Qwen，只有明确的标题推荐、自动改名或标题建议 API 操作才可能生成标题。

## 配置

可以复制 `.env.example` 作为参考，但应通过进程环境变量提供密钥，或将密钥保存在不会提交的受保护本地文件中。

| 变量 | 是否必需 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `SESSION_RENAMER_TOKEN` | 否 | 空 | 所有私人页面和操作的访问 Token；留空时关闭应用层认证 |
| `CODEX_HOME` | 否 | `~/.codex` | Codex 数据目录 |
| `SESSION_RENAMER_INDEX_PATH` | 否 | `$CODEX_HOME/session_index.jsonl` | 旧版索引路径覆盖 |
| `SESSION_RENAMER_HOST` | 否 | `127.0.0.1` | 本地监听地址 |
| `SESSION_RENAMER_PORT` | 否 | `8891` | 本地 HTTP 端口 |
| `SESSION_RENAMER_PUBLIC_URL` | 否 | 空 | FRP 辅助脚本显示的公网 HTTPS 地址，并用于绕过代理的健康检查 |
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
bash frp-tunnel.sh start
```

公网暴露前必须选择一种认证边界：

- 设置 `SESSION_RENAMER_TOKEN`，保留应用层 Token 认证。
- 或让带认证的 HTTPS 反向代理位于 VPS 内部 FRP 端口之前，保持 `SESSION_RENAMER_TOKEN` 未设置，并将 `SESSION_RENAMER_PUBLIC_URL` 设为公网 HTTPS 地址。

其他变量包括 `SESSION_RENAMER_PUBLIC_URL`、`SESSION_RENAMER_FRP_BIN`、`SESSION_RENAMER_FRP_ADMIN`、`SESSION_RENAMER_FRP_PROXY_NAME`、`SESSION_RENAMER_REMOTE_PORT`、`SESSION_RENAMER_FRP_MANAGE_CONFIG`、`SESSION_RENAMER_LOG_FILE` 和 `SESSION_RENAMER_PID_FILE`。

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

配置 `SESSION_RENAMER_PUBLIC_URL` 后，`status` 会绕过本机出站代理直接检查公网地址。收到 HTTP 响应即证明传输链路可达，其中包括带认证反向代理预期返回的 `401`。

> FRP TCP 转发本身不提供 TLS 或认证。Codex 会话可能包含源代码、凭据、个人信息和系统上下文。优先使用可信的私有网络。严禁将无 Token 模式直接暴露到公网；反向代理必须对所有管理路由强制认证。

## 安全说明

- 首次使用前备份 `~/.codex`。
- 批量改名前先检查推荐标题。
- 删除操作会修改 Codex 索引并将日志移动到本地回收目录；操作前确认当前目录和搜索筛选范围。
- 无 Token 模式会关闭应用层认证。除非带认证的 HTTPS 反向代理已经保护所有公网管理路由，否则应保留默认的本机回环监听。
- 查询参数中的 Token 可能出现在浏览器历史和中间日志中；请使用私有网络，Token 可能泄露时应及时轮换。
- 只有明确执行标题推荐或自动改名操作，或发起经过认证的标题建议 API 请求时，程序才可能将清理后的会话上下文发送给配置的模型服务商。列表页和详情页的被动刷新不会发送这些内容。

## 开发

运行完整测试：

```bash
python3 -m unittest discover -s tests -v
```

测试套件使用注入的模型伪响应，绝不会发起真实 Qwen 调用。

检查 Shell 脚本和空白格式：

```bash
bash -n run.sh frp-tunnel.sh
git diff --check
```

版本历史见 [CHANGELOG.md](./CHANGELOG.md)。

## 许可证

MIT
