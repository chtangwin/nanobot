# Himalaya 邮件设置指南

> 在 nanobot 中通过 himalaya skill 管理邮件。支持 Gmail、Yahoo、Outlook、iCloud 及任何 IMAP 邮箱。
> 当前策略：**仅支持读取和管理邮件，发送/回复/转发已禁用**（安全考虑）。

---

## 1. 安装 Himalaya CLI

### Windows

```powershell
# 方式 1: Scoop（推荐）
scoop install himalaya

# 方式 2: Cargo（如果已有 Rust 工具链）
cargo install himalaya --locked
```

如果没有 Scoop 也没有 Cargo，可手动下载：
1. 前往 https://github.com/pimalaya/himalaya/releases/latest
2. 下载 `himalaya.x86_64-windows.tgz`
3. 解压，把 `himalaya.exe` 放到 PATH 中的目录（如 `C:\Users\你的用户名\.local\bin\`）

### Linux

```bash
# 方式 1: install.sh（推荐，自动检测架构）
curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | PREFIX=~/.local sh

# 方式 2: Cargo
cargo install himalaya --locked

# 方式 3: 包管理器
# Arch:
pacman -S himalaya
# Fedora/CentOS:
dnf copr enable atim/himalaya && dnf install himalaya
```

### 验证安装

```bash
himalaya --version
# 输出类似: himalaya 1.2.0 +smtp +imap +wizard ...
```

---

## 2. 获取 App Password

大多数邮箱不允许直接使用账户密码登录 IMAP，需要生成 **App Password**（应用专用密码）。

### Gmail

1. 前往 [Google 账户安全设置](https://myaccount.google.com/security)
2. 确保已启用**两步验证**
3. 前往 [App Passwords](https://myaccount.google.com/apppasswords)
4. 选择应用名称（如输入 `himalaya`），点击"创建"
5. 复制生成的 16 位密码（形如 `abcd efgh ijkl mnop`，空格可忽略）

> Gmail 文件夹别名：Sent = `[Gmail]/Sent Mail`，Trash = `[Gmail]/Trash`，Drafts = `[Gmail]/Drafts`

### Yahoo Mail

1. 前往 [Yahoo 账户安全](https://login.yahoo.com/account/security)
2. 确保已启用**两步验证**
3. 点击 **Generate app password** 或 **App passwords**
4. 应用名称输入 `himalaya`
5. 复制生成的 16 位密码

### Outlook / Microsoft 365

**个人 Outlook.com 账户（App Password 方式）：**
1. 前往 [Microsoft 安全设置](https://account.live.com/proofs/manage/additional)
2. 启用两步验证
3. 在"App passwords"中创建新密码

**企业 Microsoft 365 账户：** 通常需要 OAuth2，配置较复杂。建议参考 [email-oauth2-proxy](https://github.com/simonrob/email-oauth2-proxy) 方案或联系 IT 管理员。

### iCloud Mail

1. 前往 [Apple ID 管理](https://appleid.apple.com/)
2. 登录后进入 **Sign-In and Security** > **App-Specific Passwords**
3. 点击 **Generate an app-specific password**
4. 输入标签 `himalaya`，复制密码

---

## 3. 存储密码

拿到 App Password 后，需要安全存储。以下按推荐程度排序：

### 方式 A: 系统密钥环（推荐，全平台通用）

在 `config.toml` 中配置：

```toml
backend.auth.type = "password"
backend.auth.keyring = "himalaya-yahoo-imap"
```

然后运行交互式配置，himalaya 会提示输入密码并自动存入系统密钥环：

```bash
himalaya account configure yahoo
```

底层使用：
- **Windows** → Windows Credential Manager
- **Linux** → libsecret / GNOME Keyring / KDE Wallet
- **macOS** → Keychain

### 方式 B: 密码命令（Linux 推荐）

先用 `pass` 存储密码：

```bash
# 安装 pass（Linux）
sudo apt install pass   # Debian/Ubuntu
# 初始化（首次使用）
pass init "your-gpg-id"
# 存储密码
pass insert email/yahoo-app-password
```

在 `config.toml` 中引用：

```toml
backend.auth.type = "password"
backend.auth.cmd = "pass show email/yahoo-app-password"
```

### 方式 C: 密码文件（Windows 简易方案）

创建密码文件（**注意：明文存储，仅适合个人机器**）：

```powershell
# 创建目录
mkdir "$env:USERPROFILE\.nanobot\himalaya"
# 写入密码（替换为你的 App Password）
"your-16-char-app-password" | Out-File -Encoding utf8 "$env:USERPROFILE\.nanobot\himalaya\yahoo-password.txt"
```

在 `config.toml` 中引用：

```toml
backend.auth.type = "password"
backend.auth.cmd = 'powershell -NoProfile -Command "Get-Content $env:USERPROFILE\\.nanobot\\himalaya\\yahoo-password.txt"'
```

### 方式 D: 明文写入配置（仅测试用）

```toml
backend.auth.type = "password"
backend.auth.raw = "your-16-char-app-password"
```

> ⚠ 不推荐。密码直接写在配置文件中，任何能读取文件的程序都能看到。

---

## 4. 编写配置文件

配置文件位置：`~/.config/himalaya/config.toml`

- **Windows**: `C:\Users\你的用户名\.config\himalaya\config.toml`
- **Linux**: `~/.config/himalaya/config.toml`

如果目录不存在，手动创建：

```bash
# Git Bash / Linux
mkdir -p ~/.config/himalaya
```

```powershell
# PowerShell
mkdir "$env:USERPROFILE\.config\himalaya" -Force
```

### 单账户示例（Yahoo）

```toml
[accounts.yahoo]
email = "you@yahoo.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.mail.yahoo.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@yahoo.com"
backend.auth.type = "password"
backend.auth.keyring = "himalaya-yahoo"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.mail.yahoo.com"
message.send.backend.port = 465
message.send.backend.encryption.type = "tls"
message.send.backend.login = "you@yahoo.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.keyring = "himalaya-yahoo"
```

### 单账户示例（Gmail）

```toml
[accounts.gmail]
email = "you@gmail.com"
display-name = "Your Name"
default = true

folder.alias.inbox = "INBOX"
folder.alias.sent = "[Gmail]/Sent Mail"
folder.alias.drafts = "[Gmail]/Drafts"
folder.alias.trash = "[Gmail]/Trash"

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@gmail.com"
backend.auth.type = "password"
backend.auth.keyring = "himalaya-gmail"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.keyring = "himalaya-gmail"
```

### 多账户示例

```toml
[accounts.yahoo]
email = "you@yahoo.com"
display-name = "Your Name"
default = true
# ... Yahoo IMAP/SMTP 配置 ...

[accounts.gmail]
email = "you@gmail.com"
display-name = "Your Name"
# ... Gmail IMAP/SMTP 配置 ...

[accounts.work]
email = "you@company.com"
display-name = "Your Name"
# ... 公司邮箱配置 ...
```

### IMAP/SMTP 服务器速查

| 邮箱 | IMAP 服务器 | IMAP 端口 | SMTP 服务器 | SMTP 端口 | SMTP 加密 |
|------|------------|-----------|------------|-----------|----------|
| Gmail | imap.gmail.com | 993 (TLS) | smtp.gmail.com | 587 (STARTTLS) | start-tls |
| Yahoo | imap.mail.yahoo.com | 993 (TLS) | smtp.mail.yahoo.com | 465 (TLS) | tls |
| Outlook.com | outlook.office365.com | 993 (TLS) | smtp.office365.com | 587 (STARTTLS) | start-tls |
| iCloud | imap.mail.me.com | 993 (TLS) | smtp.mail.me.com | 587 (STARTTLS) | start-tls |

---

## 5. 验证连接

配置完成后，测试连接：

```bash
# 列出文件夹（验证 IMAP 连接）
himalaya folder list

# 列出最近 5 封邮件
himalaya envelope list --page-size 5

# 多账户时指定账户
himalaya --account gmail folder list
```

如果成功，你会看到文件夹列表或邮件列表。如果失败，参见第 8 节排障。

---

## 6. 在 nanobot 聊天中使用

himalaya skill 已内置于 nanobot。当你在聊天中提到邮件相关操作时，nanobot 会自动使用 himalaya 命令。

### 基本测试

```
你: 看看我的收件箱有什么新邮件
nanobot: [调用 himalaya envelope list] 你有 3 封未读邮件...

你: 读一下第 42 封邮件
nanobot: [调用 himalaya message read 42] 邮件内容...
```

### 常见场景

| 你说 | nanobot 做什么 |
|------|---------------|
| "看看我的邮箱" | `himalaya envelope list` |
| "有没有 John 发来的邮件" | `himalaya envelope list from john@example.com` |
| "读一下第 15 封" | `himalaya message read 15` |
| "把这封邮件移到归档" | `himalaya message move 15 "Archive"` |
| "删掉第 8 封邮件" | `himalaya message delete 8` |
| "标记为已读" | `himalaya flag add 15 --flag seen` |
| "看看工作邮箱的邮件" | `himalaya --account work envelope list` |
| "下载第 20 封的附件" | `himalaya attachment download 20` |
| "搜索关于 meeting 的邮件" | `himalaya envelope list subject meeting` |
| "帮我发一封邮件" | ❌ nanobot 会告知发送功能已禁用 |

### 大邮箱使用技巧

如果邮箱有数千封邮件，建议：

```
你: 看最近 20 封邮件
nanobot: [调用 himalaya envelope list --page-size 20]

你: 搜索来自 boss@company.com 的邮件
nanobot: [调用 himalaya envelope list from boss@company.com]（服务端搜索，不拉全量）

你: 看第 3 页
nanobot: [调用 himalaya envelope list --page 3 --page-size 20]
```

---

## 7. 安全说明

### 当前限制

nanobot 的 himalaya skill **禁用了以下操作**：
- 发送邮件（`himalaya message write`）
- 回复邮件（`himalaya message reply`）
- 转发邮件（`himalaya message forward`）

这是有意为之的安全策略——防止 AI agent 自动发送邮件造成误操作。未来可根据需要开放。

### 密码安全

- **不要**把 App Password 存在聊天记录中
- 优先使用系统密钥环（方式 A）或 `pass`（方式 B）
- 如果使用密码文件（方式 C），确保文件权限正确：
  ```bash
  # Linux
  chmod 600 ~/.nanobot/himalaya/*-password.txt
  ```
- nanobot 的 redaction guard 会自动脱敏日志中的敏感信息，但仍应避免在聊天中提及密码

### App Password vs 账户密码

App Password 的安全优势：
- 可随时撤销，不影响主账户
- 权限受限（仅 IMAP/SMTP）
- 不能用于网页登录
- 如果泄露，撤销后重新生成即可

---

## 8. 排障

### "Authentication failed"

1. 确认使用的是 **App Password**，不是账户密码
2. 重新生成 App Password 并更新配置
3. 确认 `backend.login` 填的是完整邮箱地址

### "Connection refused" 或超时

1. 检查网络连接
2. 确认 IMAP/SMTP 服务器地址和端口正确（见第 4 节速查表）
3. 某些网络/VPN 可能阻断 993/465/587 端口

### "No configuration file found"

```bash
# 检查配置文件是否存在
# Windows (Git Bash)
cat ~/.config/himalaya/config.toml

# 或指定配置路径
himalaya -c /path/to/config.toml folder list
```

也可以通过环境变量指定：

```bash
export HIMALAYA_CONFIG=~/.config/himalaya/config.toml
```

### himalaya 命令找不到

```bash
# 检查是否在 PATH 中
which himalaya        # Linux/Git Bash
where himalaya        # CMD
```

如果用 `cargo install` 安装的，确保 `~/.cargo/bin` 在 PATH 中。

### nanobot 中 skill 未加载

```bash
# 确认 himalaya 在 PATH 中（nanobot 的 skill 检查 requires.bins）
himalaya --version

# 如果 skill 显示 available="false"，说明 himalaya 未安装或不在 PATH 中
```

---

## 附录 A: Himalaya CLI 直接使用速查

以下命令可在终端直接运行，也是 nanobot skill 内部调用的基础。

### 账户管理

```bash
# 列出所有配置的账户
himalaya account list

# 交互式配置新账户
himalaya account configure myaccount
```

### 文件夹操作

```bash
# 列出所有文件夹
himalaya folder list

# 指定账户
himalaya --account gmail folder list
```

### 列出邮件

```bash
# 默认列出 INBOX
himalaya envelope list

# 指定文件夹
himalaya envelope list --folder "Sent"
himalaya envelope list --folder "[Gmail]/Sent Mail"

# 分页
himalaya envelope list --page 1 --page-size 50
himalaya envelope list --page 2 --page-size 50

# JSON 输出
himalaya envelope list --output json
```

### 搜索邮件

```bash
# 按发件人
himalaya envelope list from john@example.com

# 按主题
himalaya envelope list subject meeting

# 组合搜索
himalaya envelope list from boss@company.com subject quarterly
```

### 读取邮件

```bash
# 按 ID 读取（纯文本）
himalaya message read 42

# 导出完整 MIME
himalaya message export 42 --full
```

### 移动 / 复制 / 删除

```bash
# 移动到文件夹
himalaya message move 42 "Archive"

# 复制到文件夹
himalaya message copy 42 "Important"

# 删除（移到 Trash）
himalaya message delete 42

# 批量操作（多个 ID）
himalaya message delete 1 2 3 4 5
himalaya message move 10 11 12 "Archive"
```

### 标记管理

```bash
# 标记已读
himalaya flag add 42 --flag seen

# 标记未读
himalaya flag remove 42 --flag seen

# 加星标
himalaya flag add 42 --flag flagged

# 取消星标
himalaya flag remove 42 --flag flagged
```

### 附件

```bash
# 下载附件到默认目录
himalaya attachment download 42

# 下载到指定目录
himalaya attachment download 42 --dir ~/Downloads
```

### 多账户操作

```bash
# 用指定账户执行任何命令
himalaya --account work envelope list
himalaya --account gmail message read 15
himalaya --account yahoo envelope list from newsletter@example.com
```

### 调试

```bash
# 查看详细日志
RUST_LOG=debug himalaya envelope list

# 完整 trace
RUST_LOG=trace RUST_BACKTRACE=1 himalaya envelope list

# Windows (PowerShell)
$env:RUST_LOG="debug"; himalaya envelope list
```
