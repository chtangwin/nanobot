# 远程节点实现说明

> 远程节点实现的技术细节

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  网关（本地）                                                │
│                                                             │
│  nanobot/                                                   │
│  ├── nodes/                                                 │
│  │   ├── config.py      - 节点配置管理                      │
│  │   ├── connection.py  - RemoteNode (SSH + WebSocket)     │
│  │   ├── manager.py     - NodeManager (多节点)              │
│  │   ├── node_server.py - 部署到远程的 WebSocket 服务器     │
│  │   └── deploy.sh      - 部署到远程的启动脚本              │
│  ├── agent/tools/                                           │
│  │   ├── nodes.py       - NodesTool (用户界面)              │
│  │   ├── shell.py       - exec 支持节点参数                 │
│  │   └── filesystem.py  - read/write/compare 支持节点参数   │
│  └── config/                                                │
│      └── nodes.json     - 存储的节点配置                    │
└─────────────────────────────────────────────────────────────┘
                         │
                SSH 隧道 (-L)
                         │
┌─────────────────────────────────────────────────────────────┐
│  远程服务器                                                  │
│                                                             │
│  /tmp/nanobot-<session>/                                    │
│  ├── node_server.py   - WebSocket 服务器 + tmux 包装器     │
│  ├── deploy.sh        - 启动脚本（检查 uv / 启动服务器）   │
│  ├── server.pid       - 服务器进程 PID                     │
│  ├── node_server.log  - 服务器日志                         │
│  └── tmux.sock        - tmux 会话 socket                   │
│                                                             │
│  tmux 会话 "nanobot"  - 保持命令上下文                      │
└─────────────────────────────────────────────────────────────┘
```

## 模块详情

### nanobot/nodes/config.py

**用途**：配置数据结构

**类**：
- `NodeConfig`：单个节点配置
  - `name`：节点标识符
  - `ssh_host`：SSH 连接字符串 (user@host)
  - `ssh_port`：SSH 端口（默认：22）
  - `ssh_key_path`：可选的 SSH 密钥路径
  - `remote_port`：远程 WebSocket 端口（默认：8765）
  - `local_port`：本地 SSH 隧道端口（自动分配）
  - `auth_token`：可选的认证令牌
  - `workspace`：默认工作目录

- `NodesConfig`：节点集合
  - `add_node()`：添加节点配置
  - `remove_node()`：移除节点
  - `get_node()`：按名称获取节点
  - `save()`：保存到文件
  - `load()`：从文件加载

**存储位置**：`~/.nanobot/nodes.json`

### nanobot/nodes/connection.py

**用途**：远程节点连接管理

**类**：
- `RemoteNode`：单个远程节点连接

**核心方法**：
- `setup()`：建立连接
  1. 生成唯一会话 ID
  2. 创建 SSH 隧道
  3. 部署并启动节点（单次操作）
  4. 连接 WebSocket
  5. 认证

- `teardown()`：清理资源（优雅关闭优先）
  1. 通过 WebSocket 发送 `shutdown` → 等待确认
  2. 如果优雅关闭失败 → SSH fallback (PID kill / fuser / tmux)
  3. 清理远程会话目录
  4. 关闭 SSH 隧道（最后）

- `execute()`：远程执行命令
  1. 发送 WebSocket 消息
  2. 等待响应
  3. 返回结果

**setup 流程**：
```
setup()
  ├─ _create_ssh_tunnel()
  │   └─ ssh -N -L local:remote user@host
  ├─ _deploy_and_start_node()
  │   ├─ 本地 staging 目录: node_server.py + deploy.sh
  │   ├─ ssh mkdir -p /tmp/nanobot-xxx/
  │   ├─ scp -r (一次性上传所有文件)
  │   └─ ssh bash deploy.sh --port PORT [--token TOKEN]
  │       deploy.sh 在远程执行：
  │       ├─ 检测 uv，未安装则 curl 自动安装
  │       ├─ fuser -k 清理旧进程
  │       ├─ setsid + disown 后台启动 node_server.py
  │       ├─ 保存 PID 到 server.pid
  │       └─ 轮询端口就绪（最多 60s）
  ├─ _connect_websocket()
  │   └─ websockets.connect(ws://localhost:port)
  └─ _authenticate()
      └─ 发送令牌，等待确认
```

**teardown 流程**：
```
teardown()
  │
  ├─ 1. _request_shutdown()           ← 优雅关闭
  │     ├─ WebSocket 发送 {"type": "shutdown"}
  │     ├─ 等待 shutdown_ack（5s 超时）
  │     ├─ 等 2s 让 node_server 完成清理
  │     │   node_server 内部：
  │     │     ├─ executor.cleanup()
  │     │     │   └─ tmux.destroy()
  │     │     │       ├─ send-keys "exit" (优雅退出 shell)
  │     │     │       └─ kill-session (兜底)
  │     │     └─ stop_event.set() → 进程正常退出
  │     └─ 关闭本地 WebSocket 对象
  │
  ├─ 2. _force_stop_node()            ← 仅当优雅关闭失败
  │     ├─ SIGTERM via server.pid → 等 1s → SIGKILL
  │     ├─ fuser -k 端口（兜底）
  │     └─ tmux kill-session（兜底）
  │
  ├─ 3. ssh rm -rf /tmp/nanobot-xxx/  ← 清理远程文件
  │
  └─ 4. _close_ssh_tunnel()           ← 最后关闭
```

### nanobot/nodes/manager.py

**用途**：管理多个远程节点

**类**：
- `NodeManager`：多节点管理器

**核心方法**：
- `add_node()`：添加并保存节点配置
- `remove_node()`：移除并断开节点
- `connect()`：连接到节点
- `disconnect()`：断开节点
- `execute()`：在节点上执行命令
- `execute_on_all()`：在所有连接的节点上执行

**连接池**：
- 维护 `name -> RemoteNode` 字典
- 执行时自动连接（如果未连接）
- 懒连接（仅在需要时连接）

### nanobot/agent/tools/nodes.py

**用途**：面向用户的节点管理工具

**重要**：`NodesTool` 接收外部 `NodeManager` 实例，与 `ExecTool`、
`ReadFileTool`、`WriteFileTool`、`CompareTool` 共享同一个管理器。
这确保通过 `NodesTool` 连接的节点对所有工具可见。

```python
# loop.py 中的初始化
self.node_manager = NodeManager(nodes_config)
self.tools.register(NodesTool(node_manager=self.node_manager))
self.tools.register(ExecTool(..., node_manager=self.node_manager))
```

**工具操作**：
| 操作 | 方法 | 说明 |
|------|------|------|
| `list` | `_list_nodes()` | 显示所有节点和状态 |
| `add` | `_add_node()` | 添加新节点配置 |
| `remove` | `_remove_node()` | 移除节点 |
| `connect` | `_connect_node()` | 连接到节点 |
| `disconnect` | `_disconnect_node()` | 断开节点 |
| `status` | `_node_status()` | 显示节点详情 |
| `exec` | `_exec_command()` | 在节点上执行命令 |

**用法**：
```
nodes action="list"
nodes action="add" name="server" ssh_host="user@host"
nodes action="exec" name="server" command="ls -la"
```

### 修改的工具

#### shell.py (ExecTool)

**变更**：
- 添加 `node_manager` 参数
- 添加 `node` 参数到 schema
- 添加 `_execute_remote()` 方法
- 委托给 NodeManager 进行远程执行

**流程**：
```
execute(command, node=None)
  ├─ if node and node_manager:
  │   └─ _execute_remote(command, node)
  │       └─ node_manager.execute(command, node)
  └─ else:
      └─ _execute_local(command)
```

#### filesystem.py (ReadFileTool, WriteFileTool)

**变更**：
- 添加 `node_manager` 参数
- 添加 `node` 参数到 schema
- 添加 `_read_remote()`、`_write_remote()` 方法
- 使用 `cat` 读取，`base64` 写入

**写入策略**：
```
_write_remote(path, content, node)
  ├─ base64.b64encode(content)
  ├─ node_manager.execute(
  │     f"mkdir -p \"$(dirname '{path}')\" && echo '{encoded}' | base64 -d > '{path}'",
  │     node
  │   )  # 路径加引号防止 shell 注入
  └─ 返回结果
```

**CompareTool**：比较本地和远程文件，输出 unified diff 格式。

### nanobot/nodes/node_server.py

**用途**：部署到远程服务器的 WebSocket 命令执行服务器

**组件**：
- `TmuxSession`：管理 tmux 会话
  - `create()`：创建会话（清理旧的残留会话）
  - `send_and_capture()`：发送命令并抓取输出（基于唯一 marker）
  - `destroy()`：优雅退出（先 `exit` → 再 `kill-session` 兜底）
- `CommandExecutor`：通过 tmux 执行命令
  - `_execute_tmux()` 根据 marker 提取输出，并返回真实 `exit_code`
- `handle_connection()`：WebSocket 处理器，接收 `stop_event` 用于优雅关闭

**tmux 输出捕获策略（已修复 prompt 误判问题）**：
```
wrapped command:
  echo __NANOBOT_START_<id>__
  <original command>
  _nanobot_ec=$?
  echo
  echo __NANOBOT_END_<id>__$_nanobot_ec

capture loop:
  1. send-keys 发送 wrapped command
  2. 轮询 capture-pane（最多 60s）直到出现 END marker
  3. 提取 START/END 之间的内容作为 output
  4. 从 END marker 解析 exit_code，计算 success=(exit_code==0)
```

这样不再依赖 `$`/`#` prompt 检测，避免输出中包含 `$`/`#` 时的误解析。

**WebSocket 协议**：
```json
// 认证
{"token": "optional-token"}
→ {"type": "authenticated", "message": "..."}

// 执行命令
{"type": "execute", "command": "ls -la"}
→ {"type": "result", "success": true, "output": "...", "error": null}

// Ping/pong
{"type": "ping"}
→ {"type": "pong"}

// 关闭连接（服务器继续运行）
{"type": "close"}

// 关闭整个服务器（优雅退出）
{"type": "shutdown"}
→ {"type": "shutdown_ack", "message": "Server shutting down"}
// 然后 stop_event.set() → 服务器退出
```

**启动方式**（通过 CLI 参数，不使用 config.json）：
```bash
# 基本启动
uv run --with websockets node_server.py --port 8765

# 带认证
uv run --with websockets node_server.py --port 8765 --token secret

# 不使用 tmux（无会话保持）
uv run --with websockets node_server.py --port 8765 --no-tmux
```

> **注意**：`--config` 参数仍然支持但不再由 `deploy.sh` 使用。
> 所有配置通过 CLI 参数传递，消除了 config.json 文件的依赖。

### nanobot/nodes/deploy.sh

**用途**：在远程服务器上部署并启动 node_server.py

**参数**：`bash deploy.sh --port PORT [--token TOKEN] [--no-tmux]`

**执行流程**：
```
1. 解析 --port / --token / --no-tmux 参数
2. ensure_uv()
   ├─ command -v uv → 已安装，跳过
   └─ 未安装 → curl (或 wget) https://astral.sh/uv/install.sh | sh
       └─ 更新 PATH ($HOME/.local/bin, $HOME/.cargo/bin)
3. fuser -k PORT/tcp → 清理旧进程
4. setsid uv run --with websockets node_server.py ... &
5. 保存 PID 到 server.pid，disown
6. 轮询端口就绪（ss / netstat / /dev/tcp，最多 60s）
   ├─ 就绪 → exit 0
   └─ 超时 → 打印日志尾部 → exit 1
```

**所有运行时文件均在 session 目录** `/tmp/nanobot-<session>/`：
- `server.pid` — 进程 PID（用于精确 kill）
- `node_server.log` — 服务器日志
- `tmux.sock` — tmux 会话 socket

## 与现有工具的集成

### 工具初始化

所有节点感知工具必须共享同一个 `NodeManager` 实例。
在 `AgentLoop._register_default_tools()` 中统一初始化：

```python
from nanobot.nodes.manager import NodeManager
from nanobot.nodes.config import NodesConfig

# 创建共享的节点管理器
config = NodesConfig.load(NodesConfig.get_default_config_path())
self.node_manager = NodeManager(config)

# 所有工具使用同一个实例
self.tools.register(NodesTool(node_manager=self.node_manager))
self.tools.register(ExecTool(..., node_manager=self.node_manager))
self.tools.register(ReadFileTool(..., node_manager=self.node_manager))
self.tools.register(WriteFileTool(..., node_manager=self.node_manager))
self.tools.register(CompareTool(node_manager=self.node_manager))
```

> **关键**：不要让 `NodesTool` 内部创建自己的 `NodeManager`，
> 否则通过它连接的节点对其他工具不可见。

### 工具参数流程

```
用户请求
    ↓
LLM 生成工具调用
    ↓
Tool.execute(command="...", node="server")
    ↓
工具检查 node 参数
    ↓
如果设置了 node：
    node_manager.execute(command, node)
    ↓
RemoteNode.execute(command)
    ↓
WebSocket → 远程 → 执行 → 返回
    ↓
结果返回用户
```

## 错误处理

### 连接错误

| 错误 | 原因 | 恢复方法 |
|------|------|----------|
| SSH 隧道失败 | SSH 不可访问 | 检查 SSH 连接 |
| WebSocket 超时 | 节点未启动 | 检查远程 Python/uv |
| 认证失败 | 无效令牌 | 检查令牌配置 |
| 连接丢失 | 网络问题 | 自动重连 |

### 命令错误

| 错误 | 原因 | 恢复方法 |
|------|------|----------|
| 超时 | 长时间运行的命令 | 使用后台模式 |
| 命令失败 | 无效命令 | 检查命令语法 |
| 会话丢失 | tmux 崩溃 | 重新连接（重建会话） |

## 测试

### 单元测试

参见 `scripts/test_remote_node.py`：

```python
# 测试配置
test_config()
test_nodes_config()
test_remote_node_config()
```

### 集成测试

使用真实 SSH 测试：

1. 设置测试虚拟机/容器
2. 添加节点配置
3. 测试连接
4. 测试命令执行
5. 验证清理

### 手动测试清单

- [ ] 添加节点配置
- [ ] 连接到节点
- [ ] 执行简单命令 (`ls`)
- [ ] 执行带 cd 的命令
- [ ] 验证会话保持
- [ ] 读取远程文件
- [ ] 写入远程文件
- [ ] 断开连接
- [ ] 验证清理（无 /tmp 文件残留）

## 性能

### 连接延迟

| 操作 | 时间 | 说明 |
|------|------|------|
| SSH 隧道 | ~2s | 首次连接 |
| scp 上传 | ~1s | 上传 node_server.py + deploy.sh |
| deploy.sh | ~3-5s | uv 已安装时 |
| deploy.sh | ~30-60s | 首次安装 uv + websockets |
| WebSocket 连接 | ~50ms | 隧道建立后 |
| 命令执行 | ~10ms | 每条命令 |
| 后续连接 | ~250ms | 使用现有节点 |

### 优化

- **连接池**：复用连接
- **懒连接**：仅在需要时连接
- **会话复用**：tmux 在命令之间保持
- **SSH 隧道保活**：由 SSH 维护

## 未来增强

### 已计划

1. **流式输出**：实时命令输出
2. **文件传输**：优化大文件处理
3. **并行执行**：在多个节点上执行
4. **健康监控**：失败时自动重连
5. **证书认证**：SSH 证书支持

### 考虑中

1. **反向 WebSocket**：远程连接到网关
2. **HTTP 后备**：非 WebSocket 选项
3. **Docker 支持**：在容器中执行
4. **Kubernetes 支持**：Pod 执行

## 安全说明

### 威胁模型

| 威胁 | 缓解措施 |
|------|----------|
| SSH 劫持 | 使用 SSH 密钥、强认证 |
| WebSocket 窥探 | 通过 SSH 隧道（加密） |
| 命令注入 | 输入验证、守卫 |
| 令牌泄露 | 不记录令牌、使用环境变量 |
| 临时文件暴露 | /tmp 权限（仅用户） |

### 最佳实践

1. 使用 SSH 密钥，而非密码
2. 为每个节点设置唯一的认证令牌
3. 限制节点权限（最小权限原则）
4. 使用工作区限制
5. 监控异常活动

## 调试

### 启用调试日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 或针对特定模块
logging.getLogger("nanobot.nodes").setLevel(logging.DEBUG)
```

### 常见问题

**问题**："SSH tunnel failed"（SSH 隧道失败）
- 检查：`ssh user@host` 可以工作
- 检查：SSH 端口正确
- 检查：防火墙允许连接

**问题**："WebSocket connection timeout"（WebSocket 连接超时）
- 检查：远程有 `curl` 或 `wget`（deploy.sh 用来安装 uv）
- 检查：远程日志 `/tmp/nanobot-xxx/node_server.log`
- 检查：deploy.sh 的输出（连接时显示在本地日志中）

**问题**："Command not found on remote"（远程找不到命令）
- 检查：远程的 PATH
- 检查：使用绝对路径
- 检查：命令在远程存在

## 贡献

### 添加新的节点感知工具

1. 在 `__init__` 中添加 `node_manager` 参数
2. 将 `node` 添加到参数 schema
3. 添加远程执行方法
4. 更新工具描述

示例：
```python
class MyTool(Tool):
    def __init__(self, node_manager=None):
        self._node_manager = node_manager

    @property
    def parameters(self):
        props = {...}
        if self._node_manager:
            props["properties"]["node"] = {...}
        return props

    async def execute(self, param, node=None):
        if node and self._node_manager:
            return await self._execute_remote(param, node)
        return await self._execute_local(param)
```

### 添加新的节点操作

1. 在 NodesTool 的 `parameters["enum"]` 中添加操作
2. 添加处理方法（`_action_name`）
3. 更新描述中的用法
4. 添加错误处理

## 参考资料

- [设计文档](./NANOBOT_NODE_ENHANCEMENT.md)
- [使用指南](./USAGE.md)
- [原始 Fork](https://github.com/EisonMe/nanobot)
