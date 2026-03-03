---
name: todos
description: 统一管理待办与笔记（task/note）、到期提醒、日报/周报与报告订阅。用户出现“记一下、加个待办、提醒我、今天有什么、逾期、完成/恢复/删除任务、批量处理、给我日报/周报、每天/每周定时发报告、取消订阅、查看订阅”等意图时触发；优先调用 `todos` 工具而非仅文本回复。
---

# Todos Skill

## 工具调用强规则（必须遵守）
- 命中 todos 意图时，先调用 `todos` 工具，再基于工具返回回复用户。
- 禁止未调用工具就声称“已添加 / 已完成 / 已订阅”。
- 工具返回 `Error:` 时，明确告知失败原因，并用修正参数重试；不要伪造成功。

## Action 速查（与 `nanobot/todos/tool.py` 对齐）
- `add`: 新增 task/note
- `query`: 查询（支持 status/category/priority/tags/keyword/type/due/include_archived）
- `done` / `undone` / `edit` / `delete`: 单条操作
- `bulk_done` / `bulk_delete` / `bulk_move`: 批量操作
- `report`: 立即生成 `daily|weekly` 报告
- `report_subscribe` / `report_unsubscribe` / `report_list`: 报告订阅管理

## 参数与校验规则（按当前代码）
- 通用：`action` 必填。
- `add`
  - 必填：`text`
  - 可选：`type(task|note)`, `category`, `due`, `remind`, `repeat`, `priority`, `tags`, `parent_id`
  - 校验：
    - `due`: `YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM`
    - `remind`: `^\d+[hmd]$`（如 `30m`, `1h`, `2d`）
- `query`
  - `due` 仅支持：`today|tomorrow|overdue|before:YYYY-MM-DD`
- `done|undone|edit|delete`
  - `id` 必填且为正整数
- `edit`
  - 至少提供一个字段：`text,due,remind,repeat,priority,tags,category`
- `bulk_done|bulk_delete`
  - 需要 `ids` 或 `category` 至少一个
  - 若提供 `ids`，必须是正整数数组
- `bulk_move`
  - 必填 `target_category`，并且需要 `ids` 或 `category`
- `report`
  - 必填 `period: daily|weekly`
- `report_subscribe`
  - 必填 `cadence: daily|weekly`
  - `time` 默认来自配置（daily/weekly 各自默认值），格式 `HH:MM`
  - `tz` 未给时按上下文/配置/系统时区推断
  - `cadence=weekly` 时 `weekday` 取传入值或默认值，且必须是 `mon..sun`
- `report_unsubscribe`
  - `subscription_id` 必填，格式必须 `daily-N` 或 `weekly-N`

## 语义要点（结合设计文档与现实现）
- 默认分类：`inbox`。
- 标签：自动 trim、转小写、去重。
- `done` 会写入完成时间；若带 `repeat`，会自动创建下一期任务。
- `undone` 会恢复为 pending。
- 提醒与订阅由独立服务轮询处理，不依赖 cron 工具调用。

## 意图映射模板（优先使用）
- “记一下：明天提交 PR”
  - `todos(action="add", text="提交 PR", due="YYYY-MM-DD")`
- “明早 10 点开会，提前 30 分钟提醒”
  - `todos(action="add", text="开会", due="YYYY-MM-DD 10:00", remind="30m")`
- “加到购物清单：买牛奶”
  - `todos(action="add", text="买牛奶", category="shopping")`
- “今天有什么待办”
  - `todos(action="query", due="today", status="pending")`
- “查逾期任务”
  - `todos(action="query", due="overdue")`
- “把 101 标记完成”
  - `todos(action="done", id=101)`
- “把 inbox 全部移动到 project-x”
  - `todos(action="bulk_move", category="inbox", target_category="project-x")`
- “给我今日日报”
  - `todos(action="report", period="daily")`
- “每晚 9 点发日报”
  - `todos(action="report_subscribe", cadence="daily", time="21:00")`
- “取消 daily-1 订阅”
  - `todos(action="report_unsubscribe", subscription_id="daily-1")`
- “看下报告订阅”
  - `todos(action="report_list")`

## 回复约束
- 成功：复述关键结果（ID、分类、数量、订阅ID）。
- 失败：原样说明校验错误并给出可执行修正（例如正确的 `due` / `subscription_id` 格式）。
- 意图不清：先澄清 1 个最关键参数，再调用工具。
