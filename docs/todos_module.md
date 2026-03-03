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
├── tool.py                  # TodosTool 主实现
├── reminder_service.py      # 到期提醒 watcher（独立于 cron）
├── report_service.py        # 日报/周报生成 + 订阅调度
└── dispatcher.py            # 通知分发抽象（chat/sms/voice）

nanobot/agent/tools/
└── todos.py                 # 薄适配层（可选）

tests/
└── test_todos.py            # 单文件测试（分 TestClass）
```

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
- [ ] 提交PR review #101 @due(2026-03-03 10:00) @priority(high) @tag(work) @remind(1h)
- [ ] 买牛奶 #102 @tag(life)

### Notes
- 📝 周会纪要 #103 @tag(reference)

---

## project-x

### Tasks
- [ ] 发布 v1.2 #104 @due(2026-03-08) @repeat(weekly)
  - [ ] 合并 release 分支 #105
  - [ ] 更新 changelog #106

---

## Archive

- [x] 跑测试 #99 @done(2026-03-01 09:40) [inbox]
```

语法：
- `- [ ]` pending task
- `- [x]` done task
- `- 📝` note
- `#N` 任务 ID（当前 `TODOS.md` 文件内唯一）
- `@timezone(IANA_ZONE)`（文件头时区声明）
- `@due(...)` / `@remind(...)` / `@repeat(...)`
- `@priority(high|medium|low)`
- `@tag(x)`（可多次）
- `@done(...)`
- `@reminded(...)`

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
    due: str | None = None
    remind: str | None = None
    repeat: Literal["daily", "weekly", "monthly", "yearly"] | None = None
    tags: list[str] = field(default_factory=list)
    parent_id: int | None = None
    children: list["TodosItem"] = field(default_factory=list)
    created_at: str = ""
    done_at: str | None = None
    reminded_at: str | None = None

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
- 当用户请求“新增、查询、完成、删除、编辑、报告、订阅报告”时，应优先调用 `todos` 工具。
- 未调用 `todos` 并拿到结果前，不应声称“已添加/已完成/已订阅”。
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
  - 必填：`id, text`
- `bulk_done | bulk_delete`
  - 必填：`ids` 或 `category`（至少一个）
- `bulk_move`
  - 必填：`target_category` + (`ids` 或 `category`)
- `report`
  - 必填：`period`（`daily|weekly`）
- `report_subscribe`
  - 必填：`cadence, time`
  - 条件必填：当 `cadence=weekly` 时，`weekday` 必填
  - 可选：`tz`
- `report_unsubscribe`
  - 必填：`subscription_id`
- `report_list`
  - 必填：无

### 7.5 字段级校验建议（Schema 细化）

- `time`: 必须匹配 `^([01]\\d|2[0-3]):[0-5]\\d$`
- `tz`: 必须是 IANA 时区字符串（运行时用 `zoneinfo.ZoneInfo` 校验）
- `due`:
  - 支持：`today|tomorrow|overdue|before:YYYY-MM-DD`
  - 或 ISO/本地格式：`YYYY-MM-DD`、`YYYY-MM-DD HH:MM`
- `priority`: `high|medium|low`
- `repeat`: `daily|weekly|monthly|yearly`
- `type`: `task|note`
- `tags[]`: 1~32 字符，trim + 英文小写 + 去重

### 7.6 设计说明

- 单工具可减少 token 开销
- action 扩展成本低
- 通过清晰 description + skill 规则，提高函数调用命中率与正确率
- 通过“action 必填约束 + 字段级校验”，显著降低 LLM 误参带来的执行失败

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
1. 扫描 `<workspace>/todos/*/*/TODOS.md`
2. 找到 `now >= due - remind` 且未提醒项
3. 通过 dispatcher 发送提醒
4. 成功后标记 `@reminded`

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

这是“真正有用”的关键能力。

### 10.1 报告类型

- **日报（daily）**：面向“明天和本周规划”，固定包含三块任务视图：
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
3. 通过 dispatcher 发送
4. 管理报告订阅（本地 JSON 持久化）
5. 周期扫描 `<workspace>/todos/*/*/report_subscriptions.json` 并触发到点推送

建议存储：
- `<workspace>/todos/<channel>/<chat_id>/report_subscriptions.json`

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

---

## 11. 通知分发抽象（为 SMS / 语音做准备）

定义统一接口：
- `NotificationDispatcher.send(notification) -> bool`

当前实现：
- `BusChannelDispatcher`（通过 nanobot channel 发消息）

未来实现：
- `SmsDispatcher`
- `VoiceCallDispatcher`

策略层（可选）：
- `NotificationPolicyResolver`
  - 先 chat 后 sms
  - 失败 fallback
  - 超时升级（`escalation_after`）

这样提醒与报告都可复用同一分发抽象（命名用 Notification 而非 Reminder，避免语义过窄）。

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
      "defaultTimezone": "Asia/Shanghai",
      "defaultDailyReportTime": "21:00",
      "defaultWeeklyWeekday": "sun",
      "defaultWeeklyReportTime": "20:00",
      "useScopeMetadata": false,
      "defaultAlertChannels": ["chat"]
    }
  }
}
```

> `defaultTimezone` 为可选项：若未配置，则自动使用 **nanobot 服务器所在时区**。

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
- `today/tomorrow/this week` 边界按“当前文件的有效时区”计算（不是固定 UTC）。

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
- 用户提到“记一下/待办/稍后做/提醒我/清单/本周总结”等。

## 工具调用强规则（必须）
- 当意图属于：新增、查询、完成、删除、编辑、报告、订阅报告时，优先调用 `todos` 工具，不要只做文本回复。
- 禁止只给口头确认（例如“已帮你记下”）而不调用工具。
- 若工具调用失败，应明确告知失败并重试合理参数，而不是假装成功。

## 参数映射规则
- “明天上午10点” -> due: "YYYY-MM-DD 10:00"
- “提前1小时提醒” -> remind: "1h"
- “每周” -> repeat: "weekly"
- “工作相关” -> tags: ["work"] 或 category: "work"

## 分类策略
- 未指定分类默认 inbox
- 用户说“放到购物清单” -> category: "shopping"
- category 不存在时自动创建

## 查询策略
- “今天有什么” -> due: "today", status: "pending"
- “逾期任务” -> due: "overdue"
- “看下 project-x” -> category: "project-x"

## 报告策略
- “给我今日日报” -> action: report, period: daily
- “每晚9点给我日报” -> action: report_subscribe, cadence: daily, time: "21:00"

## 注意事项
- 不要臆造完成状态；必须基于工具返回结果回答。
- 优先复用已有 category/tag，避免重复命名。
- 若用户意图不明确，先澄清再调用；不要盲猜。
```

### 13.2 为什么有用

- 降低 LLM 参数误填
- 统一自然语言映射行为
- 提升提醒/报告相关调用命中率

### 13.3 LLM 是否会“知道要调用 todos 工具”？

会，但需要满足以下前提：
1. `todos` 工具已在 `AgentLoop` 中注册且 `tools.todos.enabled=true`。
2. 工具 schema（name/description/parameters）清晰表达能力边界。
3. `skills/todos/SKILL.md` 提供稳定触发词与映射规则。

建议在 SKILL.md 增加一条强规则：
- 当用户意图属于“新增/查询/完成/删除/报告/订阅报告”时，**优先调用 `todos` 工具，不要只做文本回复**。

同时在 Tool description 中明确：
- `todos` 是任务管理的唯一入口（task/note/reminder/report）。
- 若未调用工具，不应声称“已添加/已完成/已订阅”。

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
- 用户：`在“发布v1.2”下面加一个子任务：更新变更日志`
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

3) 编辑
- `todos(action="edit", id=101, text="提交PR review")`

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

## 15. 与 Gateway 集成点

即使配置在 `tools.todos`，服务仍在 gateway 生命周期中装配：

1. 读取 `config.tools.todos`
2. 初始化 `TodosServiceFactory`（按 `channel/chat_id` 解析对应存储路径）
3. 注册 `TodosTool`
4. 启动 `TodosReminderService`
5. 启动 `TodosReportService`
6. 进程退出时统一 stop

---

## 16. Implementation Checklist（可直接开工）

### 16.1 代码
- [ ] 新建 `nanobot/todos/` 全部模块
- [ ] `tool.py` 实现 todos action 分发
- [ ] `tool.py` 按 7.4/7.5 实现 action 必填校验与字段级校验
- [ ] `reminder_service.py` 实现提醒轮询
- [ ] `report_service.py` 实现日报/周报与订阅
- [ ] `dispatcher.py` 抽象 + bus 实现
- [ ] `agent/loop.py` 注册 tool + 注入上下文
- [ ] `cli/commands.py` 在 gateway 生命周期启动/停止 todos services

### 16.2 配置
- [ ] `config/schema.py` 新增 `ToolsTodosConfig`
- [ ] 将配置挂到 `tools.todos`

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
2. 到期提醒只触发一次
3. 常见查询语义（today/overdue/category/tag/keyword）可稳定执行
4. 用户可自由创建并检索 tags
5. 日报/周报可即时生成
6. 日报/周报可订阅并按时推送
7. 所有能力通过 `tests/test_todos.py`

---

## 18. 最终结论

Todos 模块应以“**Python-native、Tool-native、Bus-native、Report-ready、Dispatcher-ready**”方式落地。  
配置放在 `tools.todos`，提醒独立 watcher，报告能力内建，并为未来 SMS/语音通知预留统一扩展接口。