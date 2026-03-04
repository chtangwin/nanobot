# 远程节点快速入门

5 分钟上手 nanobot 远程节点功能。

## 前置条件

### 本地（你的机器）
- ✅ 已安装 nanobot
- ✅ SSH 客户端（Git Bash 自带）
- ✅ Python 3.11+

### 远程（服务器）
- ✅ SSH 访问权限
- ✅ Python 3.11+ 或 `uv`（如果没有会自动安装）
- ✅ `tmux`（推荐，用于会话保持）

## 配置 SSH 自动登录（Windows Git Bash → Linux）

在添加远程节点之前，建议先配置 SSH 密钥认证，避免每次连接都输入密码。

### 步骤 1：检查或生成 SSH 密钥

在 Git Bash 中运行：

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

如果 `ssh-copy-id` 不可用，手动操作：

```bash
# 1. 显示公钥内容
cat ~/.ssh/id_ed25519.pub
# 或
cat ~/.ssh/id_rsa.pub

# 2. 登录到远程服务器
ssh user@192.168.1.100

# 3. 在远程服务器上执行
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "你的公钥内容" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 4. 退出远程服务器
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

编辑 `~/.ssh/config` 文件（如果不存在则创建）：

```bash
# 在 Git Bash 中
notepad ~/.ssh/config
# 或使用 vim
vim ~/.ssh/config
```

添加以下内容：

```
Host build-server
    HostName 192.168.1.100
    User your_username
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    # 或者使用 RSA
    # IdentityFile ~/.ssh/id_rsa

Host prod-server
    HostName prod.example.com
    User admin
    Port 2222
    IdentityFile ~/.ssh/id_rsa
```

保存后可以这样使用：

```bash
# 使用配置的别名
ssh build-server

# 等同于
ssh -p 22 your_username@192.168.1.100
```

### 步骤 5：配置 ssh-agent（Windows 可选）

在 Windows 上，可能需要启动 ssh-agent 来管理密钥：

```bash
# 启动 ssh-agent
eval $(ssh-agent -s)

# 添加密钥
ssh-add ~/.ssh/id_ed25519
# 或
ssh-add ~/.ssh/id_rsa

# 查看已添加的密钥
ssh-add -l
```

**让 ssh-agent 自动启动（推荐）**

在 `~/.bashrc` 或 `~/.bash_profile` 中添加：

```bash
# 启动 ssh-agent
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
# ~/.ssh          权限 700 (drwx------)
# ~/.ssh/authorized_keys  权限 600 (-rw-------)

# 如果权限不对，在远程服务器上修复：
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

**问题 2：SSH 连接被拒绝**

```bash
# 检查远程服务器 SSH 配置
ssh user@host "grep PubkeyAuthentication /etc/ssh/sshd_config"

# 应该是：
# PubkeyAuthentication yes

# 如果不是，需要修改（需要 root 权限）
```

**问题 3：Windows 路径问题**

Git Bash 中的 SSH 路径格式：

```bash
# 正确 ✅
~/.ssh/id_rsa
/c/Users/YourName/.ssh/id_rsa

# 错误 ❌
C:\Users\YourName\.ssh\id_rsa
```

### 完成后

配置完成后，添加节点时就无需每次输入密码：

```
用户：添加一个名为 "build-server" 的节点
nodes action="add" name="build-server" ssh_host="user@192.168.1.100"

Nanobot 会自动使用 SSH 密钥认证，无需密码输入！
```

## 5 分钟配置

### 步骤 1：添加第一个节点

```
你：添加一个名为 "myserver" 的节点，地址是 user@192.168.1.100

Nanobot 会调用：
nodes action="add" name="myserver" ssh_host="user@192.168.1.100"

响应：✓ 节点 'myserver' 添加成功
```

### 步骤 2：连接

```
你：连接到 myserver

Nanobot 会调用：
nodes action="connect" name="myserver"

响应：✓ 已连接到 'myserver'（会话：nanobot-a1b2c3d4）
```

### 步骤 3：执行命令

```
你：在 myserver 上运行 ls -la

Nanobot 会调用：
exec command="ls -la" node="myserver"

响应：[目录列表]
```

## 常用命令

### 列出所有节点
```
nodes action="list"
```

### 查看节点状态
```
nodes action="status" name="myserver"
```

### 执行多条命令
```
你：检查 myserver 上的磁盘空间
exec command="df -h" node="myserver"

你：/var/log 里有什么？
exec command="ls /var/log" node="myserver"

你：显示 syslog 的最后 20 行
exec command="tail -20 /var/log/syslog" node="myserver"
```

### 读取远程文件
```
read_file path="/etc/nginx/nginx.conf" node="myserver"
```

### 写入远程文件
```
write_file path="/tmp/test.txt" node="myserver" content="Hello from nanobot!"
```

## 会话保持示例

```
你：在 myserver 上 cd 到 /app
exec command="cd /app" node="myserver"

你：列出文件
exec command="ls" node="myserver"
→ [显示 /app 中的文件，会话保持！]

你：检查 git 状态
exec command="git status" node="myserver"
→ [仍在 /app 目录中]
```

## 完成后断开连接

```
nodes action="disconnect" name="myserver"

响应：✓ 已断开与 'myserver' 的连接

[远程清理会自动进行]
```

## 故障排查

### 连接失败

```bash
# 先手动测试 SSH
ssh user@192.168.1.100

# 检查远程是否有 Python
ssh user@192.168.1.100 "python3 --version"

# 检查远程是否有 uv
ssh user@192.168.1.100 "uv --version"

# 如果缺少 uv，在远程安装：
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 权限被拒绝

```bash
# 确保你的 SSH 密钥有效
ssh -i ~/.ssh/id_rsa user@192.168.1.100

# 或在添加节点时指定密钥
nodes action="add" name="myserver" ssh_host="user@host" ssh_key_path="~/.ssh/id_rsa"
```

### 找不到命令

```bash
# 使用绝对路径
exec command="/usr/bin/python3 script.py" node="myserver"

# 或先检查 PATH
exec command="echo \$PATH" node="myserver"
```

## 实际应用示例

### 部署到生产环境

```
你：将新版本部署到 prod-server

Nanobot 会：
1. exec command="cd /app && git pull" node="prod-server"
2. exec command="cd /app && npm install" node="prod-server"
3. exec command="pm2 restart myapp" node="prod-server"
4. exec command="pm2 status" node="prod-server"

30 秒完成！
```

### 在构建服务器上运行测试

```
你：在 build-server 上运行完整测试套件

Nanobot 会：
1. 连接到 build-server
2. exec command="cd /app && pytest -v" node="build-server"
3. 显示测试结果

无需手动 SSH！
```

### 分析远程代码

```
你：分析 myserver 上的代码结构

Nanobot 可以使用带节点上下文的 subagent：
1. read_file path="/app/main.py" node="myserver"
2. read_file path="/app/utils.py" node="myserver"
3. 分析代码结构
4. 提供摘要
```

## 使用技巧

1. **使用描述性名称**：`prod-server`、`build-node`、`staging-db`
2. **设置工作区**：为每个节点配置默认目录
3. **会话保持**：tmux 会保持你的工作目录
4. **自动清理**：断开时会删除所有临时文件
5. **多节点**：同时管理多个服务器

## 下一步

- 阅读详细示例：[USAGE.md](./USAGE.md)
- 阅读技术细节：[IMPLEMENTATION.md](./IMPLEMENTATION.md)
- 查看设计原理：[NANOBOT_NODE_ENHANCEMENT.md](./NANOBOT_NODE_ENHANCEMENT.md)

## 需要帮助？

常见问题和解决方案请参考 [USAGE.md#troubleshooting](./USAGE.md#troubleshooting)
