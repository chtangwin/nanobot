# 远程主机调试指南

本文档说明如何调试远程主机功能。

## 目录结构

连接建立后，远程服务器上会创建以下目录结构：

```
/tmp/nanobot-xxx/
├── remote_server.py    # WebSocket 服务器脚本
├── config.json        # 配置文件
└── remote_server.log    # 运行日志
```

`xxx` 是唯一的会话 ID（8位十六进制，例如：`a3f2b1c4`）。

## 配置文件

### 格式

```json
{
  "port": 8765,
  "token": "secret-token",
  "tmux": true
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `port` | 整数 | 8765 | WebSocket 监听端口 |
| `token` | 字符串 | null | 认证令牌（可选） |
| `tmux` | 布尔 | true | 是否使用 tmux 保持会话 |

### 查看配置

```bash
# SSH 到远程服务器
ssh root@10.0.0.174

# 查看所有 nanobot 目录
ls -la /tmp/nanobot-*/

# 查看特定会话的配置
cat /tmp/nanobot-xxx/config.json
```

## 日志文件

### 位置

`/tmp/nanobot-xxx/remote_server.log`

### 查看日志

```bash
# 查看最后 50 行
tail -50 /tmp/nanobot-xxx/remote_server.log

# 实时监控日志
tail -f /tmp/nanobot-xxx/remote_server.log

# 查看完整日志
cat /tmp/nanobot-xxx/remote_server.log
```

### 日志级别

日志使用 Python 标准日志格式：

```
2026-02-27 17:00:00,123 - INFO - Starting node_server on port 8765
2026-02-27 17:00:01,456 - INFO - Server listening on ws://0.0.0.0:8765
```

## 进程检查

### 检查 uv 进程

```bash
pgrep -a uv
```

预期输出：
```
12345 uv run --with websockets remote_server.py --config config.json
```

### 检查 Python 进程

```bash
pgrep -a python
```

预期输出：
```
12346 python remote_server.py --config config.json
```

### 检查 tmux 会话

```bash
tmux ls
```

预期输出：
```
nanobot: 1 windows
```

## 手动测试

### 1. 复制配置文件

```bash
scp root@10.0.0.174:/tmp/nanobot-xxx/config.json .
```

### 2. 本地测试

```bash
uv run --with websockets nanobot/remote/remote_server.py --config config.json
```

### 3. 测试连接

打开另一个终端：

```bash
# 使用 websocat 测试（如果安装）
websocat ws://localhost:8765

# 或使用 Python
import asyncio
import websockets
import json

async def test():
    async with websockets.connect("ws://localhost:8765") as ws:
        # 认证（如果有 token）
        await ws.send(json.dumps({"token": "secret"}))
        print(await ws.recv())
        
        # 执行命令
        await ws.send(json.dumps({"type": "execute", "command": "pwd"}))
        print(await ws.recv())

asyncio.run(test())
```

## 常见问题

### 问题 1：连接失败

**症状**：
```
Error: WebSocket connection failed
```

**调试步骤**：

1. 检查远程进程：
   ```bash
   ssh root@10.0.0.174 "pgrep -a uv"
   ```

2. 查看远程日志：
   ```bash
   ssh root@10.0.0.174 "tail -50 /tmp/nanobot-*/remote_server.log"
   ```

3. 检查端口占用：
   ```bash
   ssh root@10.0.0.174 "netstat -tlnp | grep 8765"
   ```

### 问题 2：认证失败

**症状**：
```
Error: Authentication failed
```

**解决**：检查 config.json 中的 token 是否匹配

### 问题 3：tmux 错误

**症状**：
```
Error: tmux not found
```

**解决**：
```bash
# 在远程服务器上安装 tmux
ssh root@10.0.0.174 "apt-get install tmux"
```

或者使用 `--no-tmux` 选项（不推荐）。

### 问题 4：端口被占用

**症状**：
```
Error: [Errno 98] Address already in use
```

**解决**：
```bash
# 查找占用进程
ssh root@10.0.0.174 "lsof -i :8765"

# 或使用不同端口
# 修改主机配置中的 remote_port
```

## 命令执行调试

### 查看执行信息

所有命令现在都包含调试信息：

**本地执行**：
```
🔧 Tool: exec
📁 CWD: /home/user
⚡ Cmd: ls -la

total 50
...
```

**远程执行**（正确）：
```
🔧 Tool: exec
🌐 Host: myserver
📁 CWD: (default)
⚡ Cmd: pwd

/root
```

**远程执行**（错误，绕过了 HostManager）：
```
🔧 Tool: exec
📁 CWD: /home/user
⚡ Cmd: ssh root@10.0.0.174 pwd

/root
```

### 判断标准

| 看到 | 含义 |
|------|------|
| `🌐 Host: xxx` | ✓ LLM 正确使用 host 参数 |
| 命令中有 `ssh` | ✗ LLM 绕过了 HostManager |
| `📁 CWD: /root` | 远程执行 |
| `📁 CWD: C:\Users\...` | 本地执行 |

## 日志配置

### 修改日志级别

如果需要更详细的日志，可以修改 remote_server.py：

```python
logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
```

### 添加文件日志

配置文件示例（高级）：
```json
{
  "port": 8765,
  "token": "secret",
  "tmux": true,
  "log_level": "DEBUG",
  "log_file": "/var/log/nanobot-remote.log"
}
```

注意：此功能需要修改 remote_server.py 支持。

## 性能分析

### 检查响应时间

在日志中查找时间戳：

```
2026-02-27 17:00:00.123 - INFO - Executing: ls -la
2026-02-27 17:00:00.567 - INFO - Command completed
```

响应时间：567 - 123 = 444ms

### 检查资源使用

```bash
# CPU 和内存使用
ssh root@10.0.0.174 "ps aux | grep node_server"
```

## 安全建议

### 1. 使用 Token

始终在配置文件中设置 token：

```json
{
  "port": 8765,
  "token": "strong-random-token-here",
  "tmux": true
}
```

### 2. 防火墙配置

```bash
# 只允许本地连接（通过 SSH 隧道）
ssh root@10.0.0.174 "iptables -A INPUT -p tcp --dport 8765 -s 127.0.0.1 -j ACCEPT"
ssh root@10.0.0.174 "iptables -A INPUT -p tcp --dport 8765 -j DROP"
```

### 3. 日志清理

定期清理旧的日志文件：

```bash
ssh root@10.0.0.174 "find /tmp/nanobot-* -mtime +7 -exec rm -rf {} \;"
```

## 联系支持

如果问题仍然存在：

1. 收集信息：
   - 本地命令：执行的是什么
   - 错误消息：完整的错误输出
   - 远程日志：`/tmp/nanobot-xxx/remote_server.log`
   - 配置文件：`/tmp/nanobot-xxx/config.json`

2. 提交 Issue：
   - 附上收集的信息
   - 说明复现步骤
   - 提供环境信息（OS、Python 版本等）
