# Changelog

All notable changes to this project are documented here.

## v0.7.0 - 2026-07-14

### Authentication and deployment

- Make the application token optional for loopback-only use and deployments protected by an authenticated HTTPS reverse proxy.
- Omit empty token parameters from list, detail, action, and redirect URLs.
- Add `SESSION_RENAMER_PUBLIC_URL` for public URL display and direct public health checks.
- Treat HTTP responses such as an expected reverse-proxy `401` as proof that the public transport path is reachable.
- Keep token placeholders in launcher output without printing the configured secret.

### Documentation and tests

- Document the required authentication boundary for tokenless mode in English and Chinese.
- Add regression coverage for tokenless pages, clean action URLs, protected public health checks, and secret-safe launcher output.

## v0.6.2 - 2026-07-13

### Sparse sessions

- 对只有产品名或工具名的稀疏会话继续生成三级标题，不再直接回退为原始单级标题。
- 使用 Qwen 将 `codex` 等简短输入概括为具体的咨询或使用任务。
- 删除本地关键词映射、通用标题黑名单和规则式标题兜底，标题语义统一由 Qwen 生成。
- 最近两轮标题增加独立的 Qwen 审校步骤，模型草稿中的路径改写为抽象工作状态。

## v0.6.1 - 2026-07-13

### Detail view

- 删除与推荐标题重复的“任务线索”区块，详情页直接进入完整会话记录。

## v0.6.0 - 2026-07-13

### Title recommendations

- 默认模型切换为低成本长上下文 `qwen3.5-flash`，并关闭思考模式。
- 整体任务与最近两轮状态改为两阶段独立推理，第二阶段使用整体任务作为主题上下文。
- 整体会话输入设置为保守的 10 万 Token 预算，忽略首条系统性质的 user 记录及路径等噪声。
- 一键标题推荐强制刷新当前范围内全部会话，并使用并行请求缩短等待时间。
- 拒绝空泛、问句、纯测试、路径污染和不完整标题，保证中间段以“任务”结尾。

### Session actions and UI

- 列表页和详情页增加单会话标题推荐，结果填入改名框但不自动保存。
- 推荐标题与改名输入框保持一致，一键全部改名继续使用已缓存推荐。
- 调整改名操作区布局，使文本框靠左并占据主要宽度。
- 列表页和详情页统一显示应用版本号。

## v0.5.0 - 2026-07-11

### Session management

- 使用 Codex `thread/name/set` 协议持久化新版会话标题。
- 将标题推荐与实际改名分离，推荐操作不改变会话数量或当前标题。
- 以最近一次成功改名时的内容为基准跟踪会话变化。
- 修复推荐后“会话变化”筛选结果消失的问题。

### Release

- 移除个人目录、公网 IP 和私有 FRP 名称等部署信息。
- 增加独立 Python 打包、环境变量配置和通用 FRP 脚本。
- 增加完整功能清单、安全说明及发布扫描测试。

## v0.4.0 - 2026-07-09

### Performance

- 优化首页加载流程，避免刷新列表时加载全部会话详情。
- 引入 Lazy Detail Loading，仅在需要时读取完整会话消息。
- 减少首页刷新期间的磁盘 IO 和日志解析。

### UI

- 增加右上角版本号显示。
- 优化版本号展示样式。

### Verification

- 全量测试通过：68 passed。

---

## v0.3.0 - 2026-07-09

### Performance

- 增加 session metadata cache。
- 缓存日志文件 mtime、size、preview 和 message_count。
- 避免每次刷新重复解析历史日志。

### AI Generation

- 首页刷新不再自动调用 Qwen。
- 只有用户点击“一键标题推荐”时才触发 AI 标题生成。

---

## v0.2.0 - 2026-07-09

### Initial Optimization Release

- 引入标题缓存机制。
- 优化推荐标题生成流程。
- 增加自动标题推荐相关测试。
