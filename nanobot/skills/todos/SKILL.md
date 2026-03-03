---
name: todos
description: 管理待办、笔记、提醒与日报/周报。
---

# Todos Skill

## 何时使用
- 用户提到：待办、提醒、清单、完成任务、日报、周报。

## 强规则
- 涉及新增、查询、完成、删除、编辑、报告、订阅报告时，优先调用 `todos` 工具。
- 未调用工具前，不要口头声称“已添加/已完成/已订阅”。

## 常见映射
- “记一下明天 10 点开会” → `action=add, due=YYYY-MM-DD 10:00`
- “提前 30 分钟提醒” → `remind=30m`
- “今天还有什么” → `action=query, due=today, status=pending`
- “逾期任务” → `action=query, due=overdue`
- “每晚 9 点发日报” → `action=report_subscribe, cadence=daily, time=21:00`

## 默认策略
- 未指定分类：`category=inbox`
- 标签统一小写并去重
- 参数不明确时先澄清，不盲猜
