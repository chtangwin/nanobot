# feat(todos): implement todos module with reminder/report services + validation + expanded tests

## Branch
- `feature/todos`

## Commits
- `116f935` feat(todos): add todos tool, storage, reminder and report services
- `ebf4272` feat(todos): tighten validation and align skill guidance
- `0b36012` test(todos): expand coverage for store/service/tool/reminder/report

## Summary

实现了 nanobot 的 todos 模块（Python-native 方案），包括：

1. `todos` 单工具多 action（CRUD / bulk / report / report subscriptions）
2. Markdown 持久化存储（按 `channel/chat_id` 物理隔离）
3. 独立 reminder watcher（写 `@reminded` 防重复）
4. 独立 report watcher（daily/weekly + 订阅推送）
5. gateway 生命周期接入（启动/停止统一管理）
6. skill 文件补齐并按实际代码规则更新
7. 大幅补全测试覆盖（16 个测试）

---

## Changes

### ✅ New module
- `nanobot/todos/__init__.py`
- `nanobot/todos/types.py`
- `nanobot/todos/store.py`
- `nanobot/todos/service.py`
- `nanobot/todos/tool.py`
- `nanobot/todos/reminder_service.py`
- `nanobot/todos/report_service.py`

### ✅ Integration updates
- `nanobot/config/schema.py`
  - 新增 `TodosConfig`
  - 挂载到 `ToolsConfig.todos`
- `nanobot/agent/loop.py`
  - `AgentLoop` 增加 `todos_config`
  - `_register_default_tools` 条件注册 `TodosTool`
  - `_set_tool_context` 增加 `todos`
- `nanobot/cli/commands.py`
  - `gateway()` 装配 `TodosReminderService` + `TodosReportService`
  - 注入 `_todos_notify` 回调（通过 `bus.publish_outbound`）
  - 启停纳入生命周期
  - `agent/cron run` 创建 `AgentLoop` 时透传 `todos_config`

### ✅ Skill
- 新增并更新 `nanobot/skills/todos/SKILL.md`
  - frontmatter 触发描述增强
  - action/参数校验规则与当前代码对齐
  - 增加映射模板与错误处理约束

---

## Tool actions supported (`todos`)
- `add`, `query`, `done`, `undone`, `edit`, `delete`
- `bulk_done`, `bulk_delete`, `bulk_move`
- `report`
- `report_subscribe`, `report_unsubscribe`, `report_list`

---

## Validation highlights
- `id` 必须为正整数（done/undone/edit/delete）
- `due` 格式（add/edit）`YYYY-MM-DD` or `YYYY-MM-DD HH:MM`
- `query.due` 支持：`today|tomorrow|overdue|before:YYYY-MM-DD`
- `remind` 格式：`^\d+[hmd]$`
- `report_subscribe.time`：`HH:MM`
- `report_subscribe.weekday`：`mon..sun`（weekly）
- `report_unsubscribe.subscription_id`：`daily-N|weekly-N`
- bulk `ids` 必须正整数数组

---

## Tests

### ✅ Added / expanded
- `tests/test_todos.py`（16 tests）

### ✅ Covered areas
- Store:
  - parse/serialize
  - tolerant parsing (missing id / invalid due / unknown meta)
  - `next_id` policy
  - `atomic_write` retry on `PermissionError`
  - scope path/file listing
- Service:
  - add (task/note/parent-child)
  - done/undone/repeat
  - delete cascade
  - bulk operations
  - query filters (today/tomorrow/overdue/before/category/tags/keyword/type/status/include_archived)
- Tool:
  - main action flows
  - validation error branches
  - report subscription lifecycle
- ReminderService:
  - one-time reminder semantics + skip cases
  - start/stop idempotency
- ReportService:
  - daily/weekly generation structure
  - subscription add/list/remove
  - tick dedup (`last_sent_date`)

### ✅ Verified commands
- `uv run pytest tests/test_todos.py`
- `uv run ruff check tests/test_todos.py`
- `uv run pytest tests/test_commands.py tests/test_heartbeat_service.py`

---

## GitHub PR Checklist

- [x] 新增 todos 模块（tool/store/service/reminder/report）
- [x] 集成到 `AgentLoop` 工具注册与上下文注入
- [x] 集成到 `gateway()` 生命周期
- [x] 新增 `tools.todos` 配置模型
- [x] 新增并完善 `skills/todos/SKILL.md`
- [x] 补充并通过 todos 测试
- [x] 基础回归测试通过（commands + heartbeat）
- [ ] 补充更多跨时区/跨日边界压力测试（后续）
- [ ] 进一步对齐设计文档中尚未落地的细节语义（后续）

---

## Risk Assessment

### Low risk
- 变更主要集中在新增模块 + 配置挂载 + 生命周期接入。
- 不影响既有 channel 适配器协议。

### Medium risk
- todos 解析/序列化涉及 Markdown 容错，用户手工编辑可能出现边缘格式。
- 报告与提醒为定时轮询，时间边界（分钟窗口）存在实现约束。

### Mitigations
- 已增加较全面单测覆盖 store/service/tool/reminder/report。
- 保持错误返回 `Error:` 前缀，便于上层重试与诊断。

---

## Out of scope (this PR)
- SMS/语音通知 dispatcher 抽象
- 更复杂的报告排序策略和高级统计
- 设计文档中的所有“理想态”细节逐项补齐

---

## Notes
- 仓库存在与本 PR 无关的未跟踪文档（`docs/node-remote/*`），本 PR 不包含。
