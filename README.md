# Codex会话管理工具

一个用于查看和重命名 Codex 会话索引的小型 Web 工具。

## 功能

- 读取 `/home/zhangyanbo/.codex/session_index.jsonl`
- 匹配 `~/.codex/sessions/**` 和 `~/.codex/archived_sessions/*.jsonl`
- 查看会话列表、详情和消息记录
- 在列表页直接单会话改名
- 一键把全部会话改成推荐名
- 删除无价值或已完成会话：移出索引，并把日志移入 `~/.codex/session-renamer-trash/`
- 使用 Qwen 便宜模型生成 `总摘要标题｜最近2轮摘要标题`，本地规则兜底
- 写回前自动生成 `session_index.jsonl.bak-*` 备份
- 通过 FRP 暴露到 `8.163.122.236:8887`

## 启动

```bash
cd /home/zhangyanbo/owner/xiaowangzi/projects/privacy-engineering/projects/session-renamer
export SESSION_RENAMER_TOKEN='换成一个只有你知道的口令'
bash frp-tunnel.sh start
```

访问：

```text
http://127.0.0.1:8891/?token=<SESSION_RENAMER_TOKEN>
http://8.163.122.236:8887/?token=<SESSION_RENAMER_TOKEN>
```

## 常用命令

```bash
bash frp-tunnel.sh status
bash frp-tunnel.sh stop
```

## 测试

```bash
/home/zhangyanbo/owner/xiaowangzi/projects/privacy-engineering/.venv/bin/python -m unittest discover -s projects/session-renamer/tests -v
```
