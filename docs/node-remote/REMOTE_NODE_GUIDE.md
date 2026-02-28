# 远程主机使用指南

> 在远程服务器上执行命令，就像在本地一样

## 目录

- [快速开始](#快速开始-5分钟)
- [SSH 配置指南](#ssh-配置指南)
- [核心操作](#核心操作)
- [实用示例](#实用示例)
- [配置详解](#配置详解)
- [工作原理](#工作原理)
- [高级用法](#高级用法)
- [故障排查](#故障排查)
- [最佳实践](#最佳实践)

---

## 快速开始（5分钟）

### 前置条件

**本地**：
- ✅ 已安装 nanobot
- ✅ SSH 客户端
- ✅ Python 3.11+

**远程**：
- ✅ SSH 访问权限
- ✅ `curl` 或 `wget`（用于自动安装 `uv`，如未安装）
- ✅ `tmux`（推荐，用于会话保持）

> **注意**：远程不需要预装 Python 或 uv。首次连接时 `deploy.sh` 会自动检测并安装 `uv`。

### 三步上手

**步骤 1：添加主机**

```
你："添加一个名为 'myserver' 的主机，地址是 root@10.0.0.174"

nanobot 调用：
hosts action="add" name="myserver" ssh_host="root@10.0.0.174"

响应：✓ 主机 'myserver' 添加成功
```

**步骤 2：连接**

```
你："连接到 myserver"

nanobot 调用：
hosts action="connect" name="myserver"

响应：✓ 已连接到 'myserver'（会话：nanobot-a3f2b1c4）
```

**步骤 3：执行命令**

```
你："在 myserver 上运行 pwd"

nanobot 调用：
exec command="pwd" host="myserver"

响应：
🔧 Tool: exec
🌐 Host: myserver
📁 CWD: (default)
⚡ Cmd: pwd

/root
```

就这么简单！继续阅读了解详细配置和高级用法。

---

## SSH 配置指南

在添加远程主机之前，建议先配置 SSH 密钥认证，避免每次连接都输入密码。

### 步骤 1：检查或生成 SSH 密钥

```bash
# 检查是否已有密钥
ls ~/.ssh/id_*.pub

# 如果没有，生成新密钥（按提示操作，可直接回车使用默认值）
ssh-keygen -t ed25519 -C "your_email@example.com"

# 或者使用 RSA 密钥（兼容性更好）
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
```

### 步骤 2：复制公钥到远程服务器

**方法 A：使用 ssh-copy-id（推荐）**

```bash
# 复制公钥到远程服务器（会提示输入密码）
ssh-copy-id user@192.168.1.100

# 如果 SSH 端口不是 22
ssh-copy-id -p 2222 user@192.168.1.100
```

**方法 B：手动复制**

如果 `ssh-copy-id` 不可用：

```bash
# 1. 显示公钥内容
cat ~/.ssh/id_ed25519.pub

# 2. 登录到远程服务器
ssh user@192.168.1.100

# 3. 在远程服务器上执行
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
exit
```

### 步骤 3：测试免密登录

```bash
# 应该不需要密码就能登录
ssh user@192.168.1.100

# 登录成功后退出
exit
```

### 步骤 4：配置 SSH config（可选但推荐）

编辑 `~/.ssh/config` 文件：

```bash
# Windows Git Bash
notepad ~/.ssh/config

# Linux/Mac
vim ~/.ssh/config
```

添加内容：

```
Host myserver
    HostName 10.0.0.174
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519

Host build-server
    HostName 192.168.1.100
    User your_username
    IdentityFile ~/.ssh/id_rsa
```

现在可以使用别名：

```bash
ssh myserver  # 等同于 ssh root@10.0.0.174
```

### 步骤 5：配置 ssh-agent（Windows 可选）

```bash
# 启动 ssh-agent
eval $(ssh-agent -s)

# 添加密钥
ssh-add ~/.ssh/id_ed25519

# 查看已添加的密钥
ssh-add -l
```

**自动启动（推荐）**：在 `~/.bashrc` 或 `~/.bash_profile` 中添加：

```bash
if [ -z "$SSH_AUTH_SOCK" ]; then
    eval $(ssh-agent -s)
    ssh-add ~/.ssh/id_ed25519 2>/dev/null || ssh-add ~/.ssh/id_rsa
fi
```

### 故障排查

**问题 1：仍然提示输入密码**

```bash
# 检查远程服务器上的权限
ssh user@host "ls -la ~/.ssh"

# 应该看到：
# ~/.ssh              700 (drwx------)
# ~/.ssh/authorized_keys 600 (-rw-------)

# 修复权限
ssh user@host "chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
```

**问题 2：SSH 连接被拒绝**

```bash
# 检查远程服务器 SSH 配置
ssh user@host "grep PubkeyAuthentication /etc/ssh/sshd_config"

# 应该是：PubkeyAuthentication yes
```

**问题 3：Windows 路径问题**

Git Bash 中的正确格式：

```bash
# 正确 ✅
~/.ssh/id_rsa
/c/Users/YourName/.ssh/id_rsa

# 错误 ❌
C:\Users\YourName\.ssh\id_rsa
```

---

## 核心操作

### hosts 工具

| 操作 | 说明 | 参数 |
|------|------|------|
| `list` | 列出所有主机 | - |
| `add` | 添加新主机 | `name`, `ssh_host` |
| `remove` | 移除主机 | `name` |
| `connect` | 连接到主机 | `name` |
| `disconnect` | 断开主机 | `name` |
| `status` | 查看主机状态 | `name` |
| `exec` | 执行命令（已废弃，用 exec 工具） | - |

### 支持远程的工具

这些工具支持 `host` 参数：

**exec** - 执行命令
```
# 本地
exec command="ls -la"

# 远程
exec command="ls -la" host="myserver"

# 指定工作目录
exec command="pytest" host="myserver" working_dir="/app"
```

**read_file** - 读取文件
```
# 本地
read_file path="/etc/config.py"

# 远程
read_file path="/etc/nginx.conf" host="myserver"
```

**write_file** - 写入文件
```
# 本地
write_file path="/tmp/test.txt" content="Hello"

# 远程
write_file path="/app/config.json" host="myserver" content='{"key": "value"}'
```

---

## 实用示例

### 示例 1：日常运维

**检查磁盘空间**
```
你："检查 myserver 上的磁盘空间"

nanobot：
1. exec command="df -h" host="myserver"

响应显示磁盘使用情况。
```

**查看系统负载**
```
你："myserver 负载如何？"

nanobot：
exec command="uptime" host="myserver"
```

**查看日志**
```
你："显示 myserver 上 nginx 日志的最后 20 行"

nanobot：
exec command="tail -20 /var/log/nginx/access.log" host="myserver"
```

### 示例 2：开发工作流

**远程项目分析**
```
你："分析 myserver 上 /app 项目的结构"

nanobot：
1. exec command="find /app -name '*.py' \| head -20" host="myserver"
2. read_file path="/app/main.py" host="myserver"
3. read_file path="/app/utils.py" host="myserver"
4. [分析和总结代码结构]
```

**运行测试**
```
你："在 myserver 上运行完整测试套件"

nanobot：
exec command="cd /app && pytest -v" host="myserver"

显示测试结果。
```

**Git 操作**
```
你："在 myserver 上拉取最新代码"

nanobot：
exec command="cd /app && git pull" host="myserver"

你："查看 git 状态"
exec command="cd /app && git status" host="myserver"
```

### 示例 3：部署流程

**部署到生产**
```
你："部署到 prod-server"

nanobot 自动执行：
1. exec command="cd /app && git pull origin main" host="prod-server"
2. exec command="cd /app && npm install" host="prod-server"
3. exec command="pm2 restart myapp" host="prod-server"
4. exec command="pm2 status myapp" host="prod-server"

30 秒完成部署！
```

**零停机重启**
```
你："重启 myserver 上的服务，零停机"

nanobot：
1. exec command="systemctl reload nginx" host="myserver"
2. exec command="systemctl status nginx" host="myserver"
```

### 示例 4：会话保持

tmux 会保持你的工作目录和上下文：

```
你："在 myserver 上 cd 到 /app"
→ exec command="cd /app" host="myserver"

你："列出文件"（10分钟后）
→ exec command="ls" host="myserver"
→ [显示 /app 中的文件，会话保持！]

你："检查 git 状态"
→ exec command="git status" host="myserver"
→ [仍在 /app 目录中]
```

### 示例 5：多主机管理

**在所有服务器上运行命令**
```
你："在所有服务器上检查磁盘空间"

nanobot：
1. exec command="df -h" host="server1"
2. exec command="df -h" host="server2"
3. exec command="df -h" host="server3"

汇总所有结果。
```

**批量部署**
```
你："部署到所有生产服务器"

nanobot：
1. exec command="cd /app && git pull" host="prod1"
2. exec command="cd /app && git pull" host="prod2"
3. exec command="cd /app && git pull" host="prod3"

确认所有服务器都已更新。
```

### 示例 6：文件操作

**读取配置**
```
你："查看 myserver 上的 nginx 配置"

nanobot：
read_file path="/etc/nginx/nginx.conf" host="myserver"

显示配置内容。
```

**更新配置**
```
你："更新 myserver 上的应用配置"

nanobot：
1. read_file path="/app/config.json" host="myserver"
2. [修改配置]
3. write_file path="/app/config.json" host="myserver" content="{...}"
4. exec command="systemctl restart myapp" host="myserver"
```

**创建部署脚本**
```
你："在 myserver 上创建部署脚本"

nanobot：
write_file path="/app/deploy.sh" host="myserver" content="#!/bin/bash\ngit pull\nnpm install\npm run build\npm restart"
exec command="chmod +x /app/deploy.sh" host="myserver"
```

---

## 配置详解

### 主机配置文件

配置存储在 `~/.nanobot/hosts.json`：

```json
{
  "hosts": {
    "myserver": {
      "name": "myserver",
      "ssh_host": "root@10.0.0.174",
      "ssh_port": 22,
      "ssh_key_path": null,
      "remote_port": 8765,
      "local_port": null,
      "auth_token": null,
      "workspace": null
    },
    "build-server": {
      "name": "build-server",
      "ssh_host": "user@192.168.1.100",
      "ssh_port": 22,
      "ssh_key_path": "/path/to/key",
      "workspace": "/app"
    }
  }
}
```

### 添加主机时的选项

**基本配置**
```
hosts action="add" name="myserver" ssh_host="root@10.0.0.174"
```

**使用 SSH 密钥**
```
hosts action="add" name="myserver" ssh_host="root@host" ssh_key_path="~/.ssh/id_rsa"
```

**自定义端口**
```
hosts action="add" name="myserver" ssh_host="root@host" ssh_port=2222
```

**指定工作区**
```
hosts action="add" name="myserver" ssh_host="root@host" workspace="/app"
```

**完整配置**
```
hosts action="add" \
  name="myserver" \
  ssh_host="root@10.0.0.174" \
  ssh_port=22 \
  ssh_key_path="~/.ssh/id_rsa" \
  workspace="/app"
```

---

## 工作原理

### 架构概览

```
本地                          远程
────────────────────────────────────────
nanobot agent                /tmp/nanobot-xxx/
  ├─ HostManager             ├─ remote_server.py
  ├─ RemoteHost              ├─ deploy.sh
  └─ SSH 隧道                ├─ server.pid
      ↓                      ├─ remote_server.log
WebSocket ← SSH tunnel →    ├─ tmux.sock
  ↓                          └─ tmux session "nanobot"
execute command
```

### 连接流程

```
1. 用户："连接到 myserver"
2. nanobot：创建 SSH 隧道（localhost:XXXX → remote:8765）
3. nanobot：在本地准备 staging 目录（remote_server.py + deploy.sh）
4. nanobot：scp -r 一次性上传所有文件到 /tmp/nanobot-xxx/
5. nanobot：ssh 执行 deploy.sh --port 8765 [--token ...]
   deploy.sh：
     a. 检查/安装 uv（自动 curl 下载）
     b. 清理旧进程
     c. 启动 remote_server.py（setsid + disown 后台运行）
     d. 轮询等待端口就绪（最多 60s）
6. nanobot：通过隧道连接 WebSocket
7. nanobot：认证
8. [准备执行命令]
```

### 命令执行流程

**带工作目录**：
```
1. exec command="ls" host="myserver" working_dir="/var/log"
2. nanobot → WebSocket: {"type": "execute", "command": "cd /var/log && ls"}
3. 远程：tmux send-keys 发送带唯一 marker 的 wrapped command
4. 远程：轮询 capture-pane，直到出现 END marker
5. 远程：提取 START/END 之间的输出 + exit code
6. 远程：WebSocket 响应 → nanobot
7. nanobot：向用户显示结果
```

**会话保持**：
```
命令 1: cd /app
命令 2: ls        → 仍在 /app
命令 3: git status → 仍在 /app
```

### 断开连接清理

```
teardown()
  │
  ├─ 1. 通过 WebSocket 发送 shutdown 请求
  │     node_server 收到后：
  │       ├─ 回复 shutdown_ack
  │       ├─ 清理 tmux（先 exit → 再 kill-session）
  │       └─ 设置 stop_event → 服务器正常退出
  │
  ├─ 2. 如果优雅关闭失败（超时/网络断开）→ SSH fallback
  │     ├─ SIGTERM via PID 文件 → 等 1s → SIGKILL（仅若仍活）
  │     ├─ fuser -k 端口（兜底）
  │     └─ tmux kill-session（兜底）
  │
  ├─ 3. rm -rf /tmp/nanobot-xxx/（清理远程文件）
  │
  └─ 4. 关闭 SSH 隧道（最后关闭，前面步骤需要它）

[远程服务器清理干净 — 无痕迹]
```

---

## 高级用法

### 后台任务

**启动长时间运行的服务**
```
exec command="cd /app && nohup npm run dev > /tmp/dev.log 2>&1 &" host="myserver"
```

**查看后台任务日志**
```
exec command="tail -f /tmp/dev.log" host="myserver"
```

### 管道和重定向

**组合命令**
```
exec command="ps aux \| grep nginx \| grep -v grep" host="myserver"
```

**保存输出**
```
exec command="df -h > /tmp/disk.txt" host="myserver"
```

### 多命令序列

**使用 &&**
```
exec command="cd /app && git pull && npm install && npm run build" host="myserver"
```

**使用 ;**
```
exec command="cd /app; git pull; npm install" host="myserver"
```

### Subagent 上下文

**分析远程项目**
```
你："分析 myserver 上 /app 的代码"

nanobot 生成一个带有 host="myserver" 上下文的 subagent，它可以：
- exec(command, host="myserver")
- read_file(path, host="myserver")
- write_file(path, content, host="myserver")

所有操作都自动在 myserver 上执行！
```

### 批量操作

**在多个服务器上执行**
```
你："更新所有生产服务器"

nanobot 会为每个服务器执行：
exec command="cd /app && git pull" host="prod1"
exec command="cd /app && git pull" host="prod2"
exec command="cd /app && git pull" host="prod3"
```

---

## 故障排查

### 连接失败

**症状**：
```
错误：无法连接到 'myserver'：Connection refused
```

**检查步骤**：
```bash
# 1. 测试 SSH 连接
ssh root@10.0.0.174

# 2. 检查远程是否有 curl 或 wget（deploy.sh 用来安装 uv）
ssh root@10.0.0.174 "which curl || which wget"

# 3. 检查远程 uv（首次连接会自动安装）
ssh root@10.0.0.174 "uv --version"

# 4. 手动安装 uv（如自动安装失败）
ssh root@10.0.0.174 "curl -LsSf https://astral.sh/uv/install.sh | sh"
```

### 命令超时

**症状**：
```
错误：命令在 30.0 秒后超时
```

**解决方案**：
```bash
# 使用后台模式
exec command="nohup long-running-task &" host="myserver"

# 或使用 screen/tmux
exec command="screen -dm -S task long-running-command" host="myserver"
```

### 会话丢失

**症状**：
```
cd 命令没有保持
```

**解决方案**：
```bash
# 重新连接
hosts action="connect" name="myserver"

# 会话将被重新创建
```

### 权限被拒绝

**症状**：
```
Permission denied (publickey)
```

**解决方案**：
```bash
# 检查密钥
ssh -i ~/.ssh/id_rsa root@10.0.0.174

# 或在添加主机时指定密钥
hosts action="add" name="myserver" ssh_host="root@host" ssh_key_path="~/.ssh/id_rsa"
```

### 找不到命令

**症状**：
```
command not found
```

**解决方案**：
```bash
# 使用绝对路径
exec command="/usr/bin/python3 script.py" host="myserver"

# 或检查 PATH
exec command="echo \$PATH" host="myserver"
```

### 远程日志调试

**查看远程服务器日志**：
```bash
# 1. SSH 到远程服务器
ssh root@10.0.0.174

# 2. 查看所有 nanobot 目录
ls -la /tmp/nanobot-*/

# 3. 查看日志
cat /tmp/nanobot-xxx/remote_server.log

# 4. 查看进程 PID
cat /tmp/nanobot-xxx/server.pid

# 5. 检查进程是否在运行
ps -p $(cat /tmp/nanobot-xxx/server.pid)
```

**更多调试信息**：参见 [DEBUGGING.md](./DEBUGGING.md)

---

## 最佳实践

### 1. 使用描述性的主机名称

✅ **好**：`prod-server`, `build-host`, `staging-db`
❌ **差**：`server1`, `host2`, `test`

### 2. 设置工作区

为每个主机配置默认工作目录：
```
hosts action="add" name="build-server" ssh_host="user@host" workspace="/app"
```

### 3. 使用 SSH 密钥

避免密码，使用 SSH 密钥认证：
```
ssh-keygen -t ed25519
ssh-copy-id user@host
```

### 4. 完成后断开连接

释放资源：
```
hosts action="disconnect" name="myserver"
```

### 5. 测试关键操作

在运行关键命令前先测试：
```
exec command="echo test" host="myserver"
```

### 6. 保留本地备份

在修改远程文件前保留备份：
```
read_file path="/app/config.json" host="myserver"
[保存到本地]
```

### 7. 使用版本控制

部署前检查 git 状态：
```
exec command="cd /app && git status" host="myserver"
```

### 8. 监控后台任务

启动后台任务时保存日志：
```
exec command="nohup command > /tmp/task.log 2>&1 &" host="myserver"
```

---

## 环境要求

### 本地（网关）

- Python 3.11+
- SSH 客户端
- `websockets` 包（已包含在 nanobot 依赖中）

### 远程（服务器）

- SSH 服务器
- `bash`
- `curl` 或 `wget`（用于自动安装 `uv`，如已有 `uv` 则不需要）
- `tmux`（可选，推荐用于会话保持）

> **首次连接**：`deploy.sh` 会自动检测并安装 `uv`（通过 `curl` 或 `wget`），
> 然后 `uv` 会自动管理 Python 和 `websockets` 依赖。无需手动预装。

---

## 安全考虑

1. **SSH 密钥**：使用密钥而不是密码
2. **认证令牌**：为敏感主机设置唯一令牌
3. **文件权限**：远程脚本使用 /tmp（用户级）
4. **命令守卫**：本地工具仍然阻止危险命令
5. **清理**：断开时自动删除所有临时文件

---

## 相关文档

- [调试指南](./DEBUGGING.md) - 详细的调试和故障排查
- [实现说明](./IMPLEMENTATION.md) - 技术实现细节
- [工作流程](./WORKFLOW.md) - 开发和发布工作流

---

## 需要帮助？

如果遇到问题：

1. 查看 [DEBUGGING.md](./DEBUGGING.md)
2. 检查远程日志：`/tmp/nanobot-xxx/remote_server.log`
3. 确认 SSH 连接：`ssh user@host`
4. 提交 Issue（附带日志和配置）
