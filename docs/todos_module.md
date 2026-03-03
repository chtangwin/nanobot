# Todos 模块设计方案（nanobot 对齐版）

> 目标：在 nanobot 现有 Python 架构下，实现可持久化、可提醒、可报告、可扩展的备忘录/待办系统（Todos）。

---

## 1. 目标与边界

Todos 要解决 4 件事：
1. **记录**：任务/笔记结构化落盘
2. **提醒**：到期前触达用户
3. **查询**：高频日常检索（今天、逾期、分类、标签等）
4. **复盘**：每日/每周自动报告，帮助用户持续执行

设计边界：
- 不把 Todos 做成复杂 PM 系统（不做甘特、多人协作审批）
- 优先单用户/单 chat 体验
- 保持 Markdown 可读可手改

---

## 2. 与 nanobot 架构对齐

采用当前仓库的 Python 机制：
- Tool: `nanobot.agent.tools.base.Tool`
- 注册: `AgentLoop._register_default_tools()`
- 消息发送: `MessageBus` + `OutboundMessage`
- 生命周期: gateway 启动时装配，停止时回收

不采用：
- TypeScript ToolDefinition/customTools 语义
- pad runtime 热重载模型

---

## 3. 模块结构

```text
nanobot/todos/
├── __init__.py
├── types.py                 # 数据模型
├── store.py                 # Markdown 解析/序列化/原子写
├── service.py               # CRUD/查询/done/repeat
├── tool.py                  # TodosTool 主实现（直接继承 Tool，不需要 agent/tools/ 适配层）
├── reminder_service.py      # 到期提醒 watcher（独立于 cron）
└── report_service.py        # 日报/周报生成 + 订阅调度

tests/
└── test_todos.py            # 单文件测试（分 TestClass）
```

> **设计决策**：不再设置 `nanobot/agent/tools/todos.py` 薄适配层。`TodosTool` 直接在 `nanobot/todos/tool.py` 中继承 `Tool` 基类并实现全部逻辑，与 `CronTool` 等其他工具直接注册到 `ToolRegistry` 的模式一致。
>
> **设计决策**：移除独立的 `dispatcher.py`。v1 阶段通知分发采用回调注入模式（参考 `HeartbeatService.on_notify`），将 `bus.publish_outbound` 作为回调传入 `ReminderService` 和 `ReportService`，避免过度抽象。未来需要 SMS/语音时再引入 dispatcher 抽象层。

---

## 4. 存储策略：按 channel/chat 物理隔离

### 4.1 主存储路径

每个会话独立文件：

- `<workspace>/todos/<channel>/<chat_id>/TODOS.md`

示例：
- `~/.nanobot/workspace/todos/telegram/8281248569/TODOS.md`
- `~/.nanobot/workspace/todos/slack/C01ABCDEF/TODOS.md`

### 4.2 为什么物理隔离

- 安全：天然防串数据
- 运维：便于按 chat 备份/迁移/删除
- 清晰：用户问题定位更直接

### 4.3 `@scope(...)` 策略

- 当前版本：**默认不写** `@scope(...)`
- 理由：路径已足够表达归属
- 未来一行提醒：若要做跨目录合并导出/迁移，再通过配置开关启用 `@scope(...)`

---

## 5. Markdown 格式

```markdown
# Todos
@timezone(Asia/Shanghai)

## inbox

### Tasks
- [ ] 提交PR review #101 @due(2026-03-03 10:00) @priority(high) @tag(work) @remind(1h) @created(2026-03-02 14:00)
- [ ] 买牛奶 #102 @tag(life) @created(2026-03-02 15:30)

### Notes
- 📝 周会纪要 #103 @tag(reference) @created(2026-03-02 09:00)

---

## project-x

### Tasks
- [ ] 发布 v1.2 #104 @due(2026-03-08) @repeat(weekly) @created(2026-03-01 10:00)
  - [ ] 合并 release 分支 #105 @created(2026-03-01 10:00)
  - [ ] 更新 changelog #106 @created(2026-03-01 10:00)

---

## Archive

- [x] 跑测试 #99 @created(2026-02-28 08:00) @done(2026-03-01 09:40) [inbox]
```

语法：
- `- [ ]` pending task
- `- [x]` done task
- `- 📝` note
- `#N` 任务 ID（当前 `TODOS.md` 文件内唯一）
- `@timezone(IANA_ZONE)`（文件头时区声明）
- `@due(YYYY-MM-DD)` 或 `@due(YYYY-MM-DD HH:MM)` — 截止时间
- `@remind(Nh|Nm|Nd)` — 提前提醒时长（如 `1h`=1小时, `30m`=30分钟, `1d`=1天）
- `@repeat(daily|weekly|monthly|yearly)` — 重复周期
- `@priority(high|medium|low)`
- `@tag(x)`（可多次）
- `@created(YYYY-MM-DD HH:MM)` — 创建时间（`add` 时自动写入）
- `@done(YYYY-MM-DD HH:MM)` — 完成时间（`done` 时自动写入）
- `@reminded(YYYY-MM-DD HH:MM)` — 已提醒时间戳（提醒触发后自动写入，防重复提醒）
- `[category-name]` — 仅用于 `## Archive` 中的已完成条目，记录原始所属分类

### 5.1 ID 分配策略

- 新建条目时，扫描当前 `TODOS.md` 文件中**所有 ID**（包括 `## Archive` 中的已完成项），取 `max(all_ids) + 1`。
- 若文件为空或无条目，从 `1` 开始。
- ID 一旦分配不复用，即使原条目被删除。
- 理由：避免 ID 重用导致用户混淆或提醒/报告引用错误。

### 5.2 Markdown 解析容错

用户可手动编辑 `TODOS.md`，解析器应做到：
- 缺少 `#N` 的行：跳过并 warn（不阻断其他条目解析）。
- `@due(...)` 格式不合规：保留原文但标记 `due=None`，不影响其他字段。
- 非标准缩进或空行：宽容处理，不丢失数据。
- 未知 `@xxx(...)` 标签：保留原文透传，不报错。

### 5.3 原子写入

- 写入流程：先写入临时文件（同目录下 `.TODOS.md.tmp`），成功后用 `os.replace()` 原子替换。
- Windows 注意：`os.replace()` 在 Windows 上若目标文件被其他进程打开会抛 `PermissionError`，需 catch 并重试（最多 3 次，间隔 100ms）。
- 编码：统一 UTF-8。

---

## 6. 数据模型

```python
@dataclass
class TodosItem:
    id: int
    text: str
    type: Literal["task", "note"]
    status: Literal["pending", "done"]
    category: str = "inbox"
    priority: Literal["high", "medium", "low"] | None = None
    due: str | None = None           # "YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM"
    remind: str | None = None        # "Nh" / "Nm" / "Nd"（如 "1h", "30m", "1d"）
    repeat: Literal["daily", "weekly", "monthly", "yearly"] | None = None
    tags: list[str] = field(default_factory=list)
    parent_id: int | None = None
    children: list["TodosItem"] = field(default_factory=list)
    created_at: str = ""             # "YYYY-MM-DD HH:MM"，add 时自动写入，对应 @created(...)
    done_at: str | None = None       # "YYYY-MM-DD HH:MM"，done 时自动写入，对应 @done(...)
    reminded_at: str | None = None   # "YYYY-MM-DD HH:MM"，提醒触发后写入，对应 @reminded(...)

    # 未来通知扩展
    alert_channels: list[str] = field(default_factory=lambda: ["chat"])  # chat/sms/voice_call
    escalation_after: str | None = None
```

---

## 7. Tool 设计（单工具多 action）

工具名：`todos`

action：
- `add`, `query`, `done`, `undone`, `edit`, `delete`
- `bulk_done`, `bulk_delete`, `bulk_move`
- `report`（即时生成日报/周报）
- `report_subscribe`, `report_unsubscribe`, `report_list`

### 7.1 Tool description（建议写入代码中的 description 字段）

建议使用明确、可执行导向的描述：

- `todos` 是任务管理唯一入口：task / note / reminder / report。
- 当用户请求"新增、查询、完成、删除、编辑、报告、订阅报告"时，应优先调用 `todos` 工具。
- 未调用 `todos` 并拿到结果前，不应声称"已添加/已完成/已订阅"。
- 当参数缺失时，应先补全必要参数或回退到安全默认值（如 `category=inbox`）。

### 7.2 Query 参数约定（为实现和示例对齐）

`query` 建议支持以下标准过滤：
- `status`: `pending|done|all`
- `category`: 分类名
- `priority`: `high|medium|low`
- `tags`: 标签数组
- `keyword`: 关键词
- `type`: `task|note`（可选）
- `include_archived`: `true|false`（可选，默认 `false`）
- `due`: `today|tomorrow|overdue|before:YYYY-MM-DD`

### 7.3 Report 参数约定（与报告功能对齐）

- `report`:
  - `period`: `daily|weekly`
- `report_subscribe`:
  - `cadence`: `daily|weekly`
  - `time`: `HH:MM`
  - `tz`: IANA 时区（如 `Asia/Shanghai`）
  - `weekday`: `mon|tue|wed|thu|fri|sat|sun`（仅 weekly 需要）
- `report_unsubscribe`:
  - `subscription_id`: 字符串
- `report_list`: 无必填参数

### 7.4 Action 必填约束矩阵（建议直接实现为参数校验）

- `add`
  - 必填：`text`
  - 可选：`type, category, due, remind, repeat, priority, tags, parent_id, alert_channels, escalation_after`
- `query`
  - 必填：无
  - 可选：`status, category, priority, tags, keyword, type, due, include_archived`
- `done | undone | delete`
  - 必填：`id`
- `edit`
  - 必填：`id`
  - 至少提供一个修改字段：`text, due, remind, repeat, priority, tags, category`
- `bulk_done | bulk_delete`
  - 必填：`ids` 或 `category`（至少一个）
- `bulk_move`
  - 必填：`target_category` + (`ids` 或 `category`)
- `report`
  - 必填：`period`（`daily|weekly`）
- `report_subscribe`
  - 必填：`cadence`
  - 可选：`time`（默认取 `config.default_daily_report_time` 或 `config.default_weekly_report_time`）
  - 可选：`weekday`（仅 `cadence=weekly`，默认取 `config.default_weekly_weekday`）
  - 可选：`tz`（默认按 §12.1 优先级链解析）
- `report_unsubscribe`
  - 必填：`subscription_id`
- `report_list`
  - 必填：无

### 7.5 字段级校验建议（Schema 细化）

- `time`: 必须匹配 `^([01]\\d|2[0-3]):[0-5]\\d$`
- `tz`: 必须是 IANA 时区字符串（运行时用 `zoneinfo.ZoneInfo` 校验）
- `due`:
  - 查询语义：`today|tomorrow|overdue|before:YYYY-MM-DD`
  - 赋值语义：`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM`
- `remind`: 必须匹配 `^\\d+[hmd]$`（支持单位：`h`=小时, `m`=分钟, `d`=天。如 `1h`, `30m`, `2d`）
- `priority`: `high|medium|low`
- `repeat`: `daily|weekly|monthly|yearly`
- `type`: `task|note`
- `tags[]`: 1~32 字符，trim + 英文小写 + 去重
- `subscription_id`: 由 `report_subscribe` 返回，格式为 `{cadence}-{递增数字}`（如 `daily-1`, `weekly-2`）。在 `report_subscriptions.json` 中唯一。

### 7.6 Action 语义详解

#### `done` 行为
1. 将 `- [ ]` 改为 `- [x]`。
2. 写入 `@done(YYYY-MM-DD HH:MM)`。
3. 将条目从原分类移动到 `## Archive`，并追加 `[原分类名]` 标记。
4. **若条目有 `@repeat(...)`**：在原分类中自动创建下一期新条目（新 ID、新 `@due`、新 `@created`），原条目仍归档。
   - `daily` → due + 1 天
   - `weekly` → due + 7 天
   - `monthly` → due + 1 月（同日，月末自动 clamp）
   - `yearly` → due + 1 年
   - 若原条目无 `@due`，以当前时间为基准计算下一期。
5. 子任务跟随父任务归档（若父任务 `done`，所有未完成子任务一起标记 `done` 并归档）。

#### `undone` 行为
1. 将 `- [x]` 改回 `- [ ]`。
2. 移除 `@done(...)`。
3. 从 `## Archive` 移回 `[原分类名]` 所记录的分类（若该分类已不存在，自动重建）。

#### `delete` 行为
- 从文件中物理删除该条目行（不进 Archive）。
- 若删除父任务，其所有子任务一并删除。

#### Tool 返回格式

`execute()` 返回 **纯文本字符串**（与所有 nanobot Tool 一致）：
- 成功：`"Added task #107 to inbox"`, `"Marked #101 as done"`, `"Query: 3 items found\n- [ ] ..."` 等。
- 失败：`"Error: ..."` 前缀（触发 `ToolRegistry` 自动追加重试提示）。
- `query` 返回格式化列表，每行一条目，包含 ID、文本、关键标注。
- `report` 返回完整报告 Markdown 文本。

### 7.7 设计说明

- 单工具可减少 token 开销
- action 扩展成本低
- 通过清晰 description + skill 规则，提高函数调用命中率与正确率
- 通过"action 必填约束 + 字段级校验"，显著降低 LLM 误参带来的执行失败

### 7.8 JSON Schema 参考（`TodosTool.parameters` 属性）

实现时 `parameters` 属性应返回类似以下结构：

```python
{
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["add", "query", "done", "undone", "edit", "delete",
                     "bulk_done", "bulk_delete", "bulk_move",
                     "report", "report_subscribe", "report_unsubscribe", "report_list"],
            "description": "Action to perform"
        },
        "id": {"type": "integer", "description": "Item ID (for done/undone/edit/delete)"},
        "ids": {"type": "array", "items": {"type": "integer"}, "description": "Item IDs (for bulk actions)"},
        "text": {"type": "string", "description": "Item text (for add/edit)"},
        "type": {"type": "string", "enum": ["task", "note"], "description": "Item type (default: task)"},
        "category": {"type": "string", "description": "Category name (default: inbox)"},
        "target_category": {"type": "string", "description": "Target category (for bulk_move)"},
        "due": {"type": "string", "description": "Due date: YYYY-MM-DD, YYYY-MM-DD HH:MM, today, tomorrow, overdue, before:YYYY-MM-DD"},
        "remind": {"type": "string", "description": "Remind before due: e.g. 1h, 30m, 1d"},
        "repeat": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"]},
        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "Tag list"},
        "parent_id": {"type": "integer", "description": "Parent item ID (for subtasks)"},
        "keyword": {"type": "string", "description": "Search keyword (for query)"},
        "status": {"type": "string", "enum": ["pending", "done", "all"], "description": "Filter by status (for query)"},
        "include_archived": {"type": "boolean", "description": "Include archived items (for query, default: false)"},
        "period": {"type": "string", "enum": ["daily", "weekly"], "description": "Report period"},
        "cadence": {"type": "string", "enum": ["daily", "weekly"], "description": "Subscription cadence"},
        "time": {"type": "string", "description": "Delivery time HH:MM (for report_subscribe)"},
        "tz": {"type": "string", "description": "IANA timezone (for report_subscribe)"},
        "weekday": {"type": "string", "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
        "subscription_id": {"type": "string", "description": "Subscription ID (for report_unsubscribe)"},
    },
    "required": ["action"]
}
```

> 注：仅 `action` 为全局必填，各 action 的字段约束在 `execute()` 内部校验（参见 §7.4）。这与 `CronTool` 的模式一致。

---

## 8. Category / Tag 规则

### 8.1 Category（分类）

- `add` 时传入 `category`，若不存在则自动创建（即新建 `## category`）
- 默认分类：`inbox`
- `bulk_move` 支持跨分类迁移

### 8.2 Tags（用户自定义）

允许用户自由创建标签。规范：
- 去前后空白
- 英文转小写
- 长度限制 1~32
- 条目内去重

不做固定字典约束。

---

## 9. Reminder 方案：独立 watcher（不绑定 cron）

### 9.1 设计

`TodosReminderService` 每 N 秒轮询：
1. 扫描 `<workspace>/todos/*/*/TODOS.md`（路径中的 `*/*` 即 `channel/chat_id`，用于确定通知目标）
2. 筛选满足以下条件的条目：
   - `status == "pending"` 且有 `@due(...)` 和 `@remind(...)`
   - `now >= due - remind`（当前时间已进入提醒窗口）
   - `reminded_at is None`（无 `@reminded(...)` 标注，即未提醒过）
3. 通过注入的 `on_notify` 回调发送提醒（回调签名：`async (channel, chat_id, content) -> None`）
4. 成功后在条目上写入 `@reminded(YYYY-MM-DD HH:MM)`，防止重复提醒
5. 若条目已标记 `done` 或已有 `@reminded`，跳过

> **v1 通知方式**：不使用独立 dispatcher 抽象。参考 `HeartbeatService` 模式，在 gateway 装配时将 `bus.publish_outbound` 包装为回调注入。未来需要 SMS/语音时再抽象 dispatcher 层。

### 9.2 为什么不直接复用 cron（当前阶段）

优点（独立 watcher）：
- 与 todo 状态强一致（编辑/完成即时生效）
- 不会爆炸式创建 cron job
- 逻辑集中，维护简单

缺点：
- 精度取决于轮询间隔
- 去重与恢复逻辑要自己维护

结论：
- 当前采用独立 watcher
- 后续如有必要可抽象 `ReminderScheduler`，接 cron 后端

---

## 10. Daily/Weekly 报告（新增设计）

这是"真正有用"的关键能力。

### 10.1 报告类型

- **日报（daily）**：面向"明天和本周规划"，固定包含三块任务视图：
  1. **Today**：今天剩余待办 + 今天已完成 + 今天逾期
  2. **Tomorrow**：明天到期/计划任务
  3. **This Week**：本周（含今天起到周末）重点任务与容量概览
  同时附带新增/完成统计与优先级分布。
- **周报（weekly）**：本周完成率、Top 分类、高优先级遗留、下周建议

### 10.2 生成方式

#### A. 即时报告（on-demand）
由用户触发：
- `todos(action="report", period="daily")`
- `todos(action="report", period="weekly")`

#### B. 订阅报告（scheduled digest）
用户订阅后系统自动推送：
- `todos(action="report_subscribe", cadence="daily", time="21:00", tz="Asia/Shanghai")`
- `todos(action="report_subscribe", cadence="weekly", weekday="sun", time="20:00", tz="America/Vancouver")`

### 10.3 `report_service.py` 设计

职责：
1. 读取当前 chat 的 todos
2. 生成统计摘要（不依赖 LLM，保证可测试与稳定）
3. 通过注入的 `on_notify` 回调发送（与 ReminderService 共用同一回调签名）
4. 管理报告订阅（本地 JSON 持久化）
5. 周期扫描 `<workspace>/todos/*/*/report_subscriptions.json` 并触发到点推送

建议存储：
- `<workspace>/todos/<channel>/<chat_id>/report_subscriptions.json`

`report_subscriptions.json` 结构：
```json
{
  "subscriptions": [
    {
      "id": "daily-1",
      "cadence": "daily",
      "time": "21:00",
      "tz": "Asia/Shanghai",
      "weekday": null,
      "created_at": "2026-03-02 14:00"
    },
    {
      "id": "weekly-2",
      "cadence": "weekly",
      "time": "20:00",
      "tz": "America/Vancouver",
      "weekday": "sun",
      "created_at": "2026-03-02 14:05"
    }
  ],
  "next_id": 3
}
```

- `id`：`{cadence}-{next_id}`，创建时自增 `next_id`。
- `tz`：若用户未指定，填入当前文件的有效时区（按 §12.1 优先级链）。
- ReportService 每次 tick 扫描所有 `report_subscriptions.json`，对比当前时间（转换到对应 tz）与 `time`/`weekday`，匹配则生成并发送报告。需记录 `last_sent_date` 防同日重复推送。

### 10.4 报告内容模板（标准化输出）

为便于实现、测试与用户形成稳定预期，日报/周报采用固定 Markdown 模板。

#### A. 日报模板（Daily）

```markdown
# 📅 Todos Daily Report ({{date}})

## 1) Today
- Remaining: {{today_remaining_count}}
- Completed: {{today_completed_count}}
- Overdue: {{today_overdue_count}}

### Today Priority List
- {{id}} {{text}} @due({{due}}) @priority({{priority}})

## 2) Tomorrow
- Planned: {{tomorrow_planned_count}}
- High Priority: {{tomorrow_high_count}}

### Tomorrow Key Tasks
- {{id}} {{text}} @due({{due}})

## 3) This Week
- Week Open Tasks: {{week_open_count}}
- Week High Priority Open: {{week_high_open_count}}

### This Week Focus
- {{id}} {{text}} @due({{due}})

## 4) Summary
- Added Today: {{today_added_count}}
- Daily Completion Rate: {{today_completion_rate}}%
- Suggested Next Action: {{suggestion}}  <!-- 由规则引擎生成，不依赖 LLM -->
```

#### B. 周报模板（Weekly）

```markdown
# 🗓️ Todos Weekly Report ({{week_range}})

## 1) Weekly KPI
- Added: {{week_added_count}}
- Completed: {{week_completed_count}}
- Completion Rate: {{week_completion_rate}}%
- Overdue Remaining: {{week_overdue_open_count}}

## 2) Category Breakdown
- {{category_1}}: {{count_1}}
- {{category_2}}: {{count_2}}

## 3) High Priority Open
- {{id}} {{text}} @due({{due}}) @priority(high)

## 4) Next Week Plan
- Top 3 Must-Do:
  1. {{task_a}}
  2. {{task_b}}
  3. {{task_c}}
```

实现约束：
- 字段缺失时显示 `0` 或 `-`，不要省略章节。
- 列表默认最多展示前 10 条，避免刷屏。
- 排序建议：`overdue > due asc > priority(high→low) > id asc`。
- `suggestion` 使用确定性规则（例如：先逾期、再高优先级、再最早到期），避免每次波动。

### 10.5 调度 ticker 设计

`ReminderService` 和 `ReportService` 各自运行独立的 asyncio ticker loop：
- `ReminderService`：间隔 `reminder_interval_s`（默认 60s），扫描到期提醒
- `ReportService`：间隔 `report_tick_interval_s`（默认 60s），扫描到期订阅推送

两者独立运行，互不干扰。每次 tick 均为轻量文件扫描 + 时间比较，不会产生显著开销。

### 10.6 报告数据来源：`@created(...)` 与 `@done(...)` 时间戳

日报/周报模板依赖 `today_added_count`、`week_added_count`、`week_completed_count` 等统计量。这些需要条目级时间戳支持：

- **`@created(YYYY-MM-DD HH:MM)`**：条目创建时间。`add` 时由 `service.py` 自动写入，用于统计"今日新增"、"本周新增"。
- **`@done(YYYY-MM-DD HH:MM)`**：条目完成时间。`done` 时由 `service.py` 自动写入，用于统计"今日完成"、"本周完成"。

若缺少 `@created` 标注（如手动编辑的旧条目），报告中将不计入"新增"统计；若缺少 `@done`，将不计入"完成"统计。不影响其他功能。

---

## 11. 通知分发（v1 回调注入，未来可扩展）

### 11.1 v1 方案：回调注入（当前实现）

参考 `HeartbeatService` 的 `on_execute` / `on_notify` 模式，`ReminderService` 和 `ReportService` 均接受一个 `on_notify` 回调：

```python
# 回调签名
on_notify: Callable[[str, str, str], Awaitable[None]]
# 参数：(channel, chat_id, content)
```

在 `gateway()` 装配时注入：

```python
async def _todos_notify(channel: str, chat_id: str, content: str) -> None:
    from nanobot.bus.events import OutboundMessage
    await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=content))
```

优点：
- 零额外抽象，与现有 HeartbeatService 模式完全一致
- todos 模块不直接依赖 bus，保持可测试性
- 回调可在测试中轻松 mock

### 11.2 未来扩展路径（不在 v1 范围）

当需要 SMS/语音通知时，引入 dispatcher 抽象层：
- `NotificationDispatcher.send(notification) -> bool`
- 实现：`BusChannelDispatcher`、`SmsDispatcher`、`VoiceCallDispatcher`
- 策略层：`NotificationPolicyResolver`（先 chat 后 sms、失败 fallback、超时升级）
- 届时将 `on_notify` 回调替换为 dispatcher 注入即可，无需改动 todos 核心逻辑

---

## 12. 配置设计（按你的要求放到 config.json 的 `tools`）

放在 `tools.todos`，而不是 `gateway.todos`：

```json
{
  "tools": {
    "todos": {
      "enabled": true,
      "reminderIntervalS": 60,
      "reportEnabled": true,
      "reportTickIntervalS": 60,
      "defaultTimezone": "",
      "defaultDailyReportTime": "21:00",
      "defaultWeeklyWeekday": "sun",
      "defaultWeeklyReportTime": "20:00",
      "useScopeMetadata": false,
      "defaultAlertChannels": ["chat"]
    }
  }
}
```

字段说明：
- `enabled`：是否启用 todos tool + reminder service。
- `reminderIntervalS`：ReminderService 轮询间隔（秒）。
- `reportEnabled`：是否启用报告订阅推送服务（即时报告始终可用）。
- `reportTickIntervalS`：ReportService 轮询间隔（秒）。
- `defaultTimezone`：默认时区（空字符串 = 使用服务器系统时区）。见 §12.1 优先级链。
- `defaultDailyReportTime` / `defaultWeeklyReportTime`：`report_subscribe` 时若用户未指定 `time`，使用此默认值。
- `defaultWeeklyWeekday`：`report_subscribe(cadence="weekly")` 时若用户未指定 `weekday`，使用此默认值。
- `useScopeMetadata`：是否在 Markdown 中写入 `@scope(...)` 元数据（v1 保持 `false`）。
- `defaultAlertChannels`：未来 SMS/语音扩展用，v1 仅 `["chat"]`。

### 12.1 时区处理（默认服务器时区 + 可选配置覆盖）

为保证一致性与可理解性，采用以下优先级：

1. **显式参数优先**
   - 若调用参数带 `tz`（如订阅报告），优先使用该时区。

2. **文件头时区**
   - 若 `TODOS.md` 头部存在 `@timezone(...)`，使用该时区。

3. **配置默认时区（可选）**
   - 若配置了 `tools.todos.defaultTimezone`，使用该值。

4. **服务器时区兜底**
   - 若以上都没有，使用 nanobot 运行机器的系统时区。

**内部计算（Code）**
- 统一转为 timezone-aware datetime，再转 UTC 时间戳比较与调度。
- `today/tomorrow/this week` 边界按"当前文件的有效时区"计算（不是固定 UTC）。

**Markdown 存储（.md）**
- 以人类可读为优先：`@due(YYYY-MM-DD HH:MM)`。
- 文件头必须声明：`@timezone(IANA_ZONE)`，例如 `@timezone(Asia/Shanghai)`。
- 兼容旧格式：`YYYY-MM-DD`（视为当天任务）。

**日期型 due（无时分）**
- `@due(2026-03-03)` 视为该有效时区下的当天任务。
- 逾期判定在该时区日切后（00:00）生效。

---

## 13. Skill 设计（增强 LLM 稳定性）

不是硬性必须，但强烈建议新增：
- `nanobot/skills/todos/SKILL.md`

### 13.1 SKILL.md 结构建议

```md
---
name: todos
description: 管理待办、笔记、提醒与日报/周报。
---

# Todos Skill

## 何时使用
- 用户提到"记一下/待办/稍后做/提醒我/清单/本周总结"等。

## 工具调用强规则（必须）
- 当意图属于：新增、查询、完成、删除、编辑、报告、订阅报告时，优先调用 `todos` 工具，不要只做文本回复。
- 禁止只给口头确认（例如"已帮你记下"）而不调用工具。
- 若工具调用失败，应明确告知失败并重试合理参数，而不是假装成功。

## 参数映射规则
- "明天上午10点" -> due: "YYYY-MM-DD 10:00"
- "提前1小时提醒" -> remind: "1h"
- "每周" -> repeat: "weekly"
- "工作相关" -> tags: ["work"] 或 category: "work"

## 分类策略
- 未指定分类默认 inbox
- 用户说"放到购物清单" -> category: "shopping"
- category 不存在时自动创建

## 查询策略
- "今天有什么" -> due: "today", status: "pending"
- "逾期任务" -> due: "overdue"
- "看下 project-x" -> category: "project-x"

## 报告策略
- "给我今日日报" -> action: report, period: daily
- "每晚9点给我日报" -> action: report_subscribe, cadence: daily, time: "21:00"

## 注意事项
- 不要臆造完成状态；必须基于工具返回结果回答。
- 优先复用已有 category/tag，避免重复命名。
- 若用户意图不明确，先澄清再调用；不要盲猜。
```

### 13.2 为什么有用

- 降低 LLM 参数误填
- 统一自然语言映射行为
- 提升提醒/报告相关调用命中率

### 13.3 LLM 是否会"知道要调用 todos 工具"？

会，但需要满足以下前提：
1. `todos` 工具已在 `AgentLoop` 中注册且 `tools.todos.enabled=true`。
2. 工具 schema（name/description/parameters）清晰表达能力边界。
3. `skills/todos/SKILL.md` 提供稳定触发词与映射规则。

建议在 SKILL.md 增加一条强规则：
- 当用户意图属于"新增/查询/完成/删除/报告/订阅报告"时，**优先调用 `todos` 工具，不要只做文本回复**。

同时在 Tool description 中明确：
- `todos` 是任务管理的唯一入口（task/note/reminder/report）。
- 若未调用工具，不应声称"已添加/已完成/已订阅"。

---

## 14. 用户体验示例（覆盖高频日常场景）


### 14.1 添加类

1) 普通待办
- 用户：`记一下：明天提交PR`
- 调用：`todos(action="add", text="提交PR", due="2026-03-03")`

2) 带提醒
- 用户：`明早10点开会，提前30分钟提醒`
- 调用：`todos(action="add", text="开会", due="2026-03-03 10:00", remind="30m")`

3) 创建新分类
- 用户：`加到购物清单：买牛奶`
- 调用：`todos(action="add", text="买牛奶", category="shopping")`（自动建分类）

4) 添加笔记
- 用户：`记个笔记：客户偏好蓝色主题`
- 调用：`todos(action="add", text="客户偏好蓝色主题", type="note", category="client")`

5) 重复任务
- 用户：`每周一提交周报`
- 调用：`todos(action="add", text="提交周报", due="2026-03-09 09:00", repeat="weekly")`

6) 子任务
- 用户：`在"发布v1.2"下面加一个子任务：更新变更日志`
- 调用：`todos(action="add", text="更新变更日志", parent_id=104)`

### 14.2 查询类

1) 今日待办
- `todos(action="query", due="today", status="pending")`

2) 明日待办
- `todos(action="query", due="tomorrow")`

3) 逾期
- `todos(action="query", due="overdue")`

4) 按分类
- `todos(action="query", category="shopping")`

5) 按优先级
- `todos(action="query", priority="high", status="pending")`

6) 按标签
- `todos(action="query", tags=["work", "urgent"])`

7) 关键词搜索
- `todos(action="query", keyword="PR")`

8) 仅查看笔记
- `todos(action="query", type="note")`（可选扩展过滤）

9) 查已完成
- `todos(action="query", status="done", include_archived=true)`

10) 截止日期前
- `todos(action="query", due="before:2026-03-10")`（可选语法）

### 14.3 操作类

1) 完成
- `todos(action="done", id=101)`

2) 恢复
- `todos(action="undone", id=101)`

3) 编辑文本
- `todos(action="edit", id=101, text="提交PR review")`

3b) 编辑截止日期（不改文本）
- `todos(action="edit", id=101, due="2026-03-05 18:00")`

3c) 编辑多个字段
- `todos(action="edit", id=101, priority="high", tags=["urgent"])`

4) 删除
- `todos(action="delete", id=103)`

5) 批量完成
- `todos(action="bulk_done", category="shopping")`

6) 批量移动分类
- `todos(action="bulk_move", category="inbox", target_category="project-x")`

### 14.4 报告类

1) 立即生成日报（默认包含 Today / Tomorrow / This Week 视图）
- `todos(action="report", period="daily")`

2) 立即生成周报
- `todos(action="report", period="weekly")`

3) 订阅日报
- `todos(action="report_subscribe", cadence="daily", time="21:00", tz="Asia/Shanghai")`

4) 订阅周报
- `todos(action="report_subscribe", cadence="weekly", weekday="sun", time="20:00", tz="America/Vancouver")`

5) 取消订阅
- `todos(action="report_unsubscribe", subscription_id="daily-1")`

6) 查看订阅
- `todos(action="report_list")`

---

## 15. 与 Gateway 集成点（代码级指引）

即使配置在 `tools.todos`，服务仍在 gateway 生命周期中装配。以下为具体集成位置与代码模式：

### 15.1 `config/schema.py` - 新增配置模型

```python
class TodosConfig(Base):
    """Todos tool configuration."""
    enabled: bool = True
    reminder_interval_s: int = 60
    report_enabled: bool = True
    report_tick_interval_s: int = 60
    default_timezone: str = ""  # 空字符串 = 使用服务器时区
    default_daily_report_time: str = "21:00"
    default_weekly_weekday: str = "sun"
    default_weekly_report_time: str = "20:00"
    use_scope_metadata: bool = False
    default_alert_channels: list[str] = Field(default_factory=lambda: ["chat"])

class ToolsConfig(Base):
    # ... 现有字段 ...
    todos: TodosConfig = Field(default_factory=TodosConfig)
```

### 15.2 `agent/loop.py` - Tool 注册与上下文注入

**`__init__`**：接收 `todos_config` 参数：
```python
def __init__(self, ..., todos_config: TodosConfig | None = None):
    self.todos_config = todos_config
    ...
```

**`_register_default_tools`**：条件注册 TodosTool：
```python
if self.todos_config and self.todos_config.enabled:
    from nanobot.todos.tool import TodosTool
    self.tools.register(TodosTool(
        workspace=self.workspace,
        config=self.todos_config,
    ))
```

**`_set_tool_context`**：扩展硬编码列表，加入 `"todos"`：
```python
for name in ("message", "spawn", "cron", "todos"):
    if tool := self.tools.get(name):
        if hasattr(tool, "set_context"):
            tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))
```

> 注：当前代码中 `message` tool 的 `set_context` 接收额外的 `message_id` 参数，其他 tool（含 `todos`）只接收 `(channel, chat_id)`。上述 `*([message_id] if name == "message" else [])` 是现有代码中的写法，保持一致。

`TodosTool.set_context` 签名（与 `CronTool` 一致）：
```python
def set_context(self, channel: str, chat_id: str) -> None:
    self._channel = channel
    self._chat_id = chat_id
```

### 15.3 `cli/commands.py` gateway() - 生命周期管理

参照 `CronService` 和 `HeartbeatService` 的装配模式：

```python
# 1. 读取配置
todos_cfg = config.tools.todos

# 2. 创建 AgentLoop 时传入 todos_config
agent = AgentLoop(..., todos_config=todos_cfg)

# 3. 创建通知回调
async def _todos_notify(channel: str, chat_id: str, content: str) -> None:
    await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=content))

# 4. 创建 Reminder 和 Report 服务
from nanobot.todos.reminder_service import TodosReminderService
from nanobot.todos.report_service import TodosReportService

todos_reminder = TodosReminderService(
    workspace=config.workspace_path,
    interval_s=todos_cfg.reminder_interval_s,
    on_notify=_todos_notify,
    config=todos_cfg,
)
todos_report = TodosReportService(
    workspace=config.workspace_path,
    interval_s=todos_cfg.report_tick_interval_s,
    on_notify=_todos_notify,
    config=todos_cfg,
)

# 5. 在 async def run() 中启动
async def run():
    try:
        await cron.start()
        await heartbeat.start()
        if todos_cfg.enabled:
            await todos_reminder.start()
        if todos_cfg.enabled and todos_cfg.report_enabled:
            await todos_report.start()
        ...
    finally:
        todos_report.stop()
        todos_reminder.stop()
        ...
```

---

## 16. Implementation Checklist（可直接开工）

### 16.1 代码
- [ ] 新建 `nanobot/todos/` 模块：`__init__.py`, `types.py`, `store.py`, `service.py`, `tool.py`, `reminder_service.py`, `report_service.py`
- [ ] `types.py` 实现 `TodosItem` 数据模型（含 `created_at`, `done_at`, `reminded_at`）
- [ ] `store.py` 实现 Markdown 解析（含 `@created`/`@done`/`@reminded` 全部标注）、序列化、ID 分配策略（max+1）、解析容错、原子写入（含 Windows 重试）
- [ ] `service.py` 实现 CRUD：`add`（自动写 `@created`）、`done`（写 `@done` + 归档 + repeat 自动续期）、`undone`（移回原分类）、`edit`（支持部分字段更新）、`delete`（含子任务级联）、`query`、`bulk_*` 操作
- [ ] `tool.py` 实现 todos action 分发（直接继承 `Tool`，含 `set_context()`，返回纯文本字符串）
- [ ] `tool.py` 按 §7.4/§7.5 实现 action 必填校验与字段级校验，JSON Schema 按 §7.8
- [ ] `reminder_service.py` 实现提醒轮询（`on_notify` 回调注入，写入 `@reminded` 防重复）
- [ ] `report_service.py` 实现日报/周报生成（按 §10.4 模板，基于 `@created`/`@done` 时间戳统计）+ 订阅管理（`report_subscriptions.json`，含 `last_sent_date` 防重复）
- [ ] `agent/loop.py`：接收 `todos_config` 参数，条件注册 `TodosTool`，`_set_tool_context` 列表加入 `"todos"`
- [ ] `cli/commands.py`：gateway() 中装配 `TodosReminderService` + `TodosReportService`，注入 `_todos_notify` 回调，启停纳入生命周期

### 16.2 配置
- [ ] `config/schema.py` 新增 `TodosConfig(Base)` 并挂到 `ToolsConfig.todos`

### 16.3 测试（单文件）
- [ ] 新建 `tests/test_todos.py`
- [ ] `TestTodosStore`
- [ ] `TestTodosService`
- [ ] `TestTodosTool`
- [ ] `TestTodosReminderService`
- [ ] `TestTodosReportService`
- [ ] `uv run pytest tests/test_todos.py`

### 16.4 Skill
- [ ] 新建 `nanobot/skills/todos/SKILL.md`
- [ ] 覆盖添加/查询/报告映射示例

---

## 17. 验收标准（DoD）

1. 不同 channel/chat 存储完全分离
2. 到期提醒只触发一次（`@reminded` 标记去重）
3. 常见查询语义（today/overdue/category/tag/keyword/type/status）可稳定执行
4. 用户可自由创建并检索 tags
5. `done` 正确归档 + `repeat` 自动续期 + `undone` 正确恢复
6. `edit` 支持部分字段更新（不强制改 text）
7. 日报/周报可即时生成（基于 `@created`/`@done` 时间戳统计）
8. 日报/周报可订阅并按时推送（不重复推送）
9. Markdown 手动编辑后解析不崩溃（容错）
10. 原子写入不丢数据（含 Windows 环境）
11. 所有能力通过 `tests/test_todos.py`

---

## 18. 最终结论

Todos 模块应以"**Python-native、Tool-native、Bus-native、Report-ready、Callback-injectable**"方式落地。  
配置放在 `tools.todos`，提醒独立 watcher，报告能力内建。v1 通知采用回调注入（与 HeartbeatService 一致），未来需要 SMS/语音时再引入 dispatcher 抽象层。

### 关键设计决策总结

| 决策 | 方案 | 理由 |
|------|------|------|
| Tool 实现位置 | `nanobot/todos/tool.py` 直接继承 `Tool` | 无需 `agent/tools/todos.py` 适配层，减少间接层 |
| 通知分发 | 回调注入 `on_notify` | 与 HeartbeatService 模式一致，v1 不过度抽象 |
| ID 分配 | `max(all_ids) + 1`（含 Archive） | 避免 ID 重用导致混淆 |
| 上下文注入 | `_set_tool_context` 列表扩展 | 必须加入 `"todos"` 否则拿不到 channel/chat_id |
| 配置模型 | `TodosConfig` 挂到 `ToolsConfig.todos` | 与 `tools.web`、`tools.exec` 平级 |
| Markdown 写入 | 临时文件 + `os.replace()`（Windows 重试） | 原子性 + 跨平台安全 |
| 调度 ticker | Reminder 与 Report 各自独立 loop | 互不干扰，逻辑清晰 |