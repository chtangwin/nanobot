### PR Title
feat(todos): add todos tool with reminder/report services and expanded tests

### Labels (建议)
- `feature`
- `tooling`
- `tests`
- `enhancement`

### Reviewers (建议角色)
- 1 位熟悉 `agent/loop.py` / tools 注册的同学
- 1 位熟悉 `cli/commands.py` 生命周期的同学
- 1 位偏测试质量的同学（可选）

---

## What this PR does

实现 todos 模块并接入 nanobot 主流程，包含：

- 新增 `todos` tool（CRUD / bulk / report / 订阅管理）
- 新增 Markdown 存储层（按 `channel/chat_id` 隔离）
- 新增提醒服务（独立 watcher，`@reminded` 去重）
- 新增报告服务（daily/weekly + 订阅推送）
- 接入 gateway 生命周期与 AgentLoop tool context
- 新增并完善 `skills/todos/SKILL.md`
- 扩展 `tests/test_todos.py`（16 tests）

---

## Key files

- New: `nanobot/todos/*`
- Updated:
  - `nanobot/config/schema.py` (adds `ToolsConfig.todos`)
  - `nanobot/agent/loop.py` (registers `TodosTool`, sets context)
  - `nanobot/cli/commands.py` (wires reminder/report services)
  - `nanobot/skills/todos/SKILL.md`
  - `tests/test_todos.py`

---

## Validation

已通过：

- `uv run pytest tests/test_todos.py`
- `uv run ruff check tests/test_todos.py`
- `uv run pytest tests/test_commands.py tests/test_heartbeat_service.py`

---

## Notes for reviewers

- 本 PR 以“可用 v1”为目标，优先实现单用户/单 chat 的核心流程。
- 仍有部分设计文档“理想态细节”可后续补齐（如更多边界/时间窗口细化）。
- 与本 PR 无关的 `docs/node-remote/*` 未跟踪文件未纳入提交。

---

## Suggested follow-ups (separate PRs)

- 更细的跨时区/跨日边界测试
- 更严格的 markdown 异常输入压力测试
- 报告统计/排序策略进一步对齐设计文档细项
