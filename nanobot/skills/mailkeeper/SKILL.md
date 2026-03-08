---
name: mailkeeper
description: Run the external mailsweep Mailkeeper backend for model-based daily mailbox triage, incremental processing of new email, dry-run preview, safe apply runs, first-time mailbox state initialization, and recurring scheduled Yahoo/Gmail IMAP classification and folder routing. Use when the user wants automated daily processing, inbox triage, recurring mailbox sorting, preview/apply of batch routing, or scheduled handling of recent emails. Do not use for one-off manual Himalaya operations like listing folders, reading a single message, or direct ad-hoc message moves.
---

# Mailkeeper

Use the external `mailsweep` project as the backend.

- Run backend script: `scripts/mailkeeper_run.py`
- Read generated `summary.json` / `chat_report`
- Return a polished chat summary
- Use `cron` for recurring runs

Do **not** reimplement mailbox logic inside this skill.

Use `mailkeeper` for recurring, model-based, batch mailbox processing.
Use `himalaya` for direct/manual email operations such as listing folders, reading one message, searching ad hoc, or moving a specific message by hand.

## Project location

Preferred setup: put the mailsweep project path in `~/.nanobot/config.json`.

Example:

```json
{
  "tools": {
    "mailkeeper": {
      "projectDir": "/c/Dev_Home/dev_pi/mailsweep",
      "workDir": "~/.nanobot/workspace/mailkeeper"
    }
  }
}
```

Supported keys:

- `tools.mailkeeper.projectDir` / `project_dir`
- `tools.mailkeeper.workDir` / `work_dir`

If needed, pass `--project-dir` or `--work-dir` to the wrapper script.

Environment variable `MAILKEEPER_PROJECT_DIR` is still supported as a fallback, but `config.json` is recommended.

## Runtime location

Mailkeeper runtime state lives in the configured `workDir`.

Default:

```text
~/.nanobot/workspace/mailkeeper/
```

Expect these subdirectories:

- `state/`
- `locks/`
- `runs/`
- `latest/`

Treat this as persistent runtime state, not a temp folder.

## Safety rules

1. Never delete mail. Mailkeeper only moves mail.
2. Prefer dry-run unless the user explicitly asks for apply.
3. Prefer source folders `INBOX` or `Bulk`.
4. If state is missing, run `--init-state` first.
5. Do not force first-time apply unless the user explicitly accepts bootstrap apply risk.
6. If apply is blocked, report the block reason instead of bypassing it.
7. Respond from the cleaned summary, not raw logs.

## Typical trigger phrases

Prefer `mailkeeper` when requests sound like:

English:
- run daily mailbox triage
- process new emails
- sort my inbox automatically
- preview what mailkeeper would do
- do a dry-run for Yahoo INBOX
- apply mailbox routing for recent emails
- initialize mailbox processing state
- set up daily email processing
- schedule recurring inbox sorting
- classify and move recent emails in batch

中文：
- 运行每日邮箱分拣
- 处理新邮件
- 自动整理收件箱
- 先预览一下会怎么分类
- 对 Yahoo INBOX 做一次 dry-run
- 正式执行最近邮件的分类移动
- 初始化邮箱处理状态
- 设置每日邮件自动处理
- 定时整理收件箱
- 批量分类并移动最近邮件

Prefer `himalaya` instead when the request is about:

- listing folders
- reading one specific message
- searching mail ad hoc
- manually moving one message
- downloading attachments
- inspecting account configuration
- 列出邮箱文件夹
- 查看某封邮件
- 搜索邮件
- 手动移动某封邮件
- 下载附件
- 检查 Himalaya 账户配置

## Commands

### Dry-run

```bash
uv run --project "/c/Dev_Home/dev_pi/nanobot" python "nanobot/skills/mailkeeper/scripts/run_mailkeeper.py" --account yahoo --folder INBOX
```

### Apply

```bash
uv run --project "/c/Dev_Home/dev_pi/nanobot" python "nanobot/skills/mailkeeper/scripts/run_mailkeeper.py" --account yahoo --folder INBOX --apply
```

### Init one mailbox

```bash
uv run --project "/c/Dev_Home/dev_pi/nanobot" python "nanobot/skills/mailkeeper/scripts/run_mailkeeper.py" --account yahoo --folder INBOX --init-state
```

### Intentional bootstrap apply

Use only when the user explicitly wants first-time apply without prior state:

```bash
uv run --project "/c/Dev_Home/dev_pi/nanobot" python "nanobot/skills/mailkeeper/scripts/run_mailkeeper.py" --account yahoo --folder INBOX --apply --allow-bootstrap-apply
```

## Multi-mailbox initialization

If the user is deploying Mailkeeper for multiple accounts/folders, initialize state from the `mailsweep` project:

```bash
uv run scripts/init_mailkeeper_states.py --accounts yahoo gmail work other --include-bulk
```

## Response pattern

1. Run the wrapper script.
2. Read JSON output.
3. Use `chat_report` if present.
4. Mention `summary_path` or `metadata_path` only when useful.
5. If bootstrap mode is active, say so clearly.
6. If apply was blocked, explain why and what to run next.

## Scheduling

Use the `cron` skill/tool for recurring runs.

Prefer high-level tasks such as:

- `Run mailkeeper dry-run for Yahoo INBOX and send me a summary`
- `Run mailkeeper apply for Yahoo INBOX and send me a summary`

Avoid embedding long shell commands in cron unless necessary.

## Cron natural-language templates

Use short, high-level scheduling phrases that describe intent, mailbox, mode, and reporting.

English:
- Every morning at 8am, run mailkeeper dry-run for Yahoo INBOX and send me a summary.
- Every day at 9am, run mailkeeper dry-run for Yahoo Bulk and report the result.
- Weekdays at 7:30am, process new Yahoo INBOX emails with mailkeeper dry-run and send me a summary.
- Every evening at 6pm, run mailkeeper apply for Yahoo INBOX and send me the final summary.
- Every 2 hours, run mailkeeper dry-run for Gmail INBOX and report planned moves.
- Every day at 8am, initialize mailkeeper state for Yahoo INBOX if needed, then run dry-run and send me a summary.

中文：
- 每天早上 8 点，对 Yahoo INBOX 运行一次 mailkeeper dry-run，并把摘要发给我。
- 每天上午 9 点，对 Yahoo Bulk 运行一次 mailkeeper dry-run，并汇报结果。
- 每个工作日早上 7 点半，对 Yahoo INBOX 做一次 mailkeeper dry-run，处理新邮件并发送摘要。
- 每天晚上 6 点，对 Yahoo INBOX 执行 mailkeeper apply，并把最终摘要发给我。
- 每隔 2 小时，对 Gmail INBOX 运行一次 mailkeeper dry-run，并汇报计划移动结果。
- 每天早上 8 点，如果 Yahoo INBOX 还没初始化 state，就先初始化，再运行 dry-run，并把摘要发给我。

Preferred wording patterns:
- start with time or frequency
- include `mailkeeper`
- include account + folder
- say `dry-run` or `apply` explicitly
- ask for a summary/report back in chat

## References

When architecture or deployment details matter, read these docs in the `mailsweep` project:

- `docs/MAILKEEPER_ARCHITECTURE.md`
- `docs/MAILKEEPER_DEPLOYMENT.md`
