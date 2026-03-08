---
name: himalaya
description: "CLI for direct manual email operations via IMAP/SMTP. Use `himalaya` to list folders, read specific messages, search inboxes, inspect accounts, move/copy/delete individual emails, manage folders, or download attachments from the terminal. Supports Gmail, Yahoo, Outlook, iCloud, and any IMAP provider. Use when the user asks for one-off email inspection or explicit manual operations. Do not use for Mailkeeper-style model-based daily triage, incremental processing, scheduled mailbox routing, or batch preview/apply workflows. Sending/replying/forwarding is disabled for safety."
metadata: '{"nanobot":{"emoji":"📧","requires":{"bins":["himalaya"]}}}'
---
# Himalaya Email CLI

Himalaya is a CLI email client that lets you manage emails from the terminal using IMAP, SMTP, Notmuch, or Sendmail backends.

Use this skill for direct/manual mailbox operations.
Use `mailkeeper` instead for recurring model-based triage, daily processing, dry-run/apply workflows, and scheduled mailbox routing.

## Typical trigger phrases

Prefer `himalaya` when requests sound like:

English:
- list my mail folders
- read the latest email
- search inbox for a sender or subject
- inspect a specific message
- move this email manually
- copy one message to another folder
- download an attachment
- check my himalaya account config

中文：
- 列出邮箱文件夹
- 查看最新邮件
- 按发件人或主题搜索邮件
- 查看某封邮件
- 手动移动邮件
- 复制邮件到另一个文件夹
- 下载附件
- 检查 Himalaya 账户配置

Prefer `mailkeeper` instead when the request is about:

- daily mailbox triage
- automated inbox sorting
- dry-run / apply batch routing
- incremental processing of new mail
- first-time state initialization
- recurring scheduled mailbox handling
- 每日邮箱分拣
- 自动整理收件箱
- dry-run / apply 批量路由
- 增量处理新邮件
- 初始化处理状态
- 定时处理邮箱

## References

- `references/configuration.md` (config file setup + IMAP/SMTP authentication)

## Prerequisites

1. Himalaya CLI installed (`himalaya --version` to verify)
2. A configuration file at `~/.config/himalaya/config.toml`
3. IMAP/SMTP credentials configured (password stored securely)

## Configuration Setup

Run the interactive wizard to set up an account (replace `default` with
any name you want, e.g. `gmail`, `work`):

```bash
himalaya account configure default
```

Or create `~/.config/himalaya/config.toml` manually:

```toml
[accounts.personal]
email = "you@example.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@example.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show email/imap"  # or use keyring

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"
```

If you are using 163 mail account, add `backend.extensions.id.send-after-auth = true` in the config file to ensure proper functionality.

## Common Operations

### List Folders

```bash
himalaya folder list
```

### List Emails

List emails in INBOX (default):

```bash
himalaya envelope list
```

List emails in a specific folder:

```bash
himalaya envelope list --folder "Sent"
```

List with pagination:

```bash
himalaya envelope list --page 1 --page-size 20
```

If meet with error, try:

```bash
himalaya envelope list -f INBOX -s 1
```

### Search Emails

```bash
himalaya envelope list from john@example.com subject meeting
```

### Read an Email

Read email by ID (shows plain text):

```bash
himalaya message read 42
```

Export raw MIME:

```bash
himalaya message export 42 --full
```

### Reply / Forward / Write (Disabled)

**Do not send, reply, forward, or compose emails.** These operations are
disabled for safety. Avoid using any of the following commands:

- `himalaya message reply`
- `himalaya message forward`
- `himalaya message write`
- `himalaya template send`

When the user ask you to do so, just reply you don't have such ability.

### Move/Copy Emails

Move to folder:

```bash
himalaya message move 42 "Archive"
```

Copy to folder:

```bash
himalaya message copy 42 "Important"
```

### Delete an Email

```bash
himalaya message delete 42
```

### Manage Flags

Add flag:

```bash
himalaya flag add 42 --flag seen
```

Remove flag:

```bash
himalaya flag remove 42 --flag seen
```

## Multiple Accounts

List accounts:

```bash
himalaya account list
```

Use a specific account:

```bash
himalaya --account work envelope list
```

## Attachments

Save attachments from a message:

```bash
himalaya attachment download 42
```

Save to specific directory:

```bash
himalaya attachment download 42 --dir ~/Downloads
```

## Output Formats

Most commands support `--output` for structured output:

```bash
himalaya envelope list --output json
himalaya envelope list --output plain
```

## Debugging

Enable debug logging:

```bash
RUST_LOG=debug himalaya envelope list
```

Full trace with backtrace:

```bash
RUST_LOG=trace RUST_BACKTRACE=1 himalaya envelope list
```

## Tips

- Use `himalaya --help` or `himalaya <command> --help` for detailed usage.
- Message IDs are relative to the current folder; re-list after folder changes.
- Store passwords securely using system keyring, `pass`, or a command that outputs the password.
- Use `--output json` for structured output when processing results programmatically.
- Use `--page` and `--page-size` for large mailboxes to avoid timeouts.
