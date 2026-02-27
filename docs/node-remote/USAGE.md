# 远程节点使用指南

> 如何使用 nanobot 的远程执行能力

## 概述

远程节点允许 nanobot 在远程机器上执行命令，就像在本地一样。该系统：

- ✅ 在远程服务器上无需安装任何软件
- ✅ 保持会话上下文（tmux）
- ✅ 自动管理 SSH 隧道
- ✅ 断开后自动清理（零痕迹）

## 快速开始

### 1. 添加远程节点

```
用户："为 build-server 添加一个节点，地址是 user@192.168.1.100"

Nanobot 会调用：
nodes action="add" name="build-server" ssh_host="user@192.168.1.100"
```

### 2. 连接到节点

```
用户："连接到 build-server"

Nanobot 会调用：
nodes action="connect" name="build-server"
```

### 3. 远程执行命令

```
用户："在 build-server 上运行 ls -la"

Nanobot 会调用：
exec command="ls -la" node="build-server"
```

## 可用操作

### nodes 工具操作：

| 操作 | 说明 | 必需参数 |
|------|------|---------|
| `list` | 列出所有已配置的节点 | - |
| `add` | 添加新节点 | `name`、`ssh_host` |
| `remove` | 移除节点 | `name` |
| `connect` | 连接到节点 | `name` |
| `disconnect` | 断开节点连接 | `name` |
| `status` | 获取节点状态 | `name` |
| `exec` | 在节点上执行命令 | `name`、`command` |

## 支持节点的工具

这些工具支持 `node` 参数：

### exec

```
# 本地执行
exec command="ls -la"

# 远程执行
exec command="ls -la" node="build-server"

# 指定工作目录
exec command="pytest" node="build-server" working_dir="/app"
```

### read_file

```
# 本地文件
read_file path="/etc/config.py"

# 远程文件
read_file path="/etc/nginx.conf" node="prod-server"
```

### write_file

```
# 本地文件
write_file path="/tmp/test.txt" content="Hello"

# 远程文件
write_file path="/app/config.json" node="build-server" content='{"key": "value"}'
```

## 使用示例

### 示例 1：分析远程项目

```
用户："连接到 build-server 并分析 /app 项目"

Nanobot：
1. nodes action="connect" name="build-server"
2. exec command="find /app -name '*.py' | head -20" node="build-server"
3. read_file path="/app/main.py" node="build-server"
4. read_file path="/app/utils.py" node="build-server"
5. [分析和总结]
```

### 示例 2：在远程服务器上运行测试

```
用户："在 build-server 上运行测试套件"

Nanobot：
exec command="cd /app && pytest -v" node="build-server"
```

### 示例 3：部署到生产环境

```
用户："将新版本部署到 prod-server"

Nanobot：
1. exec command="cd /app && git pull origin main" node="prod-server"
2. exec command="cd /app && pip install -r requirements.txt" node="prod-server"
3. exec command="systemctl restart myapp" node="prod-server"
4. exec command="systemctl status myapp" node="prod-server"
```

### 示例 4：会话保持

```
用户："在 build-server 上 cd 到 /project"
→ exec command="cd /project" node="build-server"

用户："列出文件"（10分钟后）
→ exec command="ls" node="build-server"
→ [显示 /project 中的文件 - 会话保持！]
```

## 配置

### 节点配置文件

节点配置存储在 `~/.nanobot/nodes.json`：

```json
{
  "nodes": {
    "build-server": {
      "name": "build-server",
      "ssh_host": "user@192.168.1.100",
      "ssh_port": 22,
      "ssh_key_path": null,
      "remote_port": 8765,
      "local_port": null,
      "auth_token": null,
      "workspace": "/app"
    },
    "prod-server": {
      "name": "prod-server",
      "ssh_host": "admin@prod.example.com",
      "ssh_port": 22,
      "ssh_key_path": "/path/to/key",
      "workspace": "/var/www"
    }
  }
}
```

### 添加节点时指定选项

```
# 基本配置
nodes action="add" name="server" ssh_host="user@host"

# 使用 SSH 密钥
nodes action="add" name="server" ssh_host="user@host" ssh_key_path="~/.ssh/id_rsa"

# 自定义端口
nodes action="add" name="server" ssh_host="user@host" ssh_port=2222

# 指定工作区
nodes action="add" name="server" ssh_host="user@host" workspace="/app"
```

## 工作原理

### 连接流程

```
1. 用户："连接到 build-server"
2. 网关：SSH → build-server
3. 网关：部署 node_server.py 到 /tmp/nanobot-xxx/
4. 网关：生成并上传 config.json
5. 网关：启动 uv run node_server.py --config config.json
6. 网关：创建 SSH 隧道（localhost:XXXX → remote:8765）
7. 网关：通过隧道连接 WebSocket
8. 网关：在远程创建 tmux 会话
9. [准备执行命令]
```

### 命令执行流程

```
1. 用户："在 build-server 上运行 pytest"
2. 网关：WebSocket 消息 → 远程节点
3. 远程：tmux send-keys "pytest"
4. 远程：tmux capture-pane
5. 远程：WebSocket 响应 → 网关
6. 网关：向用户显示结果
```

### 断开连接时的清理

```
1. 网关：关闭 WebSocket
2. 网关：杀死远程的 tmux 会话
3. 网关：rm -rf /tmp/nanobot-xxx/
4. 网关：关闭 SSH 隧道
5. [远程服务器清理干净 - 无痕迹]
```

## 环境要求

### 本地（网关）

- Python 3.11+
- SSH 客户端
- `websockets` 包（已在 nanobot 依赖中）

### 远程

- SSH 服务器
- Python 3.11+（或 uv 会安装它）
- `bash`
- `tmux`（可选，用于会话保持）

### 首次远程连接

首次连接时，远程必须具备：
- `uv`（如果缺失会通过 curl 安装程序自动安装）

示例：
```bash
# 在远程上，如果缺少 uv：
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 故障排查

### 连接失败

```
用户："连接到 build-server"
响应："错误：无法连接到 'build-server'：..."

检查：
1. SSH 访问：ssh user@host
2. 远程 Python：python3 --version
3. 远程 uv：uv --version
4. 网络连接
```

### 命令超时

```
用户："在 build-server 上运行长时间任务"
响应："错误：命令在 30.0 秒后超时"

解决方案：
- 使用后台模式：exec command="nohup command &" node="server"
- 或增加工具配置中的超时时间
```

### 会话丢失

```
用户："我的 cd 没有保持！"
→ tmux 可能崩溃了

解决方案：
- 重新连接：nodes action="connect" name="server"
- 会话将被重新创建
```

## 高级用法

### 多节点管理

```
用户："在所有服务器上运行测试"

Nanobot：
1. nodes action="connect" name="build-server"
2. nodes action="connect" name="test-server"
3. exec command="pytest" node="build-server"
4. exec command="pytest" node="test-server"
```

### 使用 Subagent 处理远程任务

```
用户："分析 build-server 上的代码"

Nanobot：
1. 生成带有 node="build-server" 上下文的 subagent
2. Subagent 使用：
   - exec(command, node="build-server")
   - read_file(path, node="build-server")
   - write_file(path, content, node="build-server")
3. Subagent 返回分析结果
```

### 后台任务

```
用户："在 build-server 上后台启动开发服务器"

exec command="cd /app && nohup npm run dev > /tmp/dev.log 2>&1 &" node="build-server"

# 稍后查看日志
exec command="tail -f /tmp/dev.log" node="build-server"
```

## 安全考虑

1. **SSH 密钥**：使用 SSH 密钥而不是密码
2. **认证令牌**：为每个节点设置唯一的令牌
3. **文件权限**：远程脚本使用 /tmp（用户级）
4. **命令守卫**：本地 exec 工具仍然会阻止危险命令

## 最佳实践

1. **工作区**：为每个节点设置默认工作区
2. **节点命名**：使用描述性的节点名称（prod-1、staging 等）
3. **会话管理**：完成后断开连接以释放资源
4. **测试**：在运行关键命令前测试连接
5. **备份**：在本地保留关键远程文件的备份

## 相关文档

- [设计文档](./NANOBOT_NODE_ENHANCEMENT.md)
- [实现说明](./IMPLEMENTATION.md)
