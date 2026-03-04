# Nanobot Remote Host: 远程执行能力

> 让 nanobot 能够在远程机器上执行命令，就像本地一样。

---

## 1. 概述

### 背景

当前 nanobot 的局限：

| 场景 | nanobot | 期望 |
|------|---------|------|
| 本地开发 | ✅ subagent + 工具 | - |
| 远程简单命令 | ✅ SSH + exec | - |
| 远程复杂分析 | ❌ 需要手动拉回代码 | ✅ subagent 使用远程资源 |

### 目标

- Subagent 可以使用远程资源（文件、命令输出），就像本地一样
- 像本地一样使用 read_file、exec 等工具
- 无需在远程安装额外软件
- 会话保持（cd 目录后，ls 仍在同一目录）
- 零痕迹（结束后清理一切）

---

## 2. 设计思路

### 三种方案

| 方案 | 远程安装 | 复杂度 | 性能 | 会话保持 | 推荐场景 |
|------|---------|--------|------|----------|----------|
| **纯 SSH** | ❌ | ⭐ | 中 | ❌ | 简单命令 |
| **SSH + WebSocket** | ❌ | ⭐⭐ | 高 | ❌ | 无需会话保持 |
| **SSH 隧道 + WebSocket + tmux** | ❌ | ⭐⭐ | 高 | ✅ | ✅ 个人使用推荐 |
| **反向 WebSocket + tmux** | ❌ | ⭐⭐ | 高 | ✅ | 多远程 / 团队场景 |

### 方案一：SSH 隧道 + WebSocket + tmux (推荐)

> 两种方式都需要先用 SSH 部署脚本，区别在于后续通信方式。

**推荐原因（个人使用场景）：**
- 远程 SSH 端口通常已开放（服务器标配）
- 本地无需开放端口
- 架构简单，一条 SSH 隧道搞定

```
┌─────────────────────────────────────────────────────────┐
│  本地 Gateway                                            │
│                                                          │
│  1. SSH 进入远程，部署 remote_server.py              │
│  2. 启动 WebSocket Server                              │
│  3. 建立 SSH 隧道: ssh -L 18765:localhost:18765 ... │
│  4. 通过隧道与远程 WebSocket 通信                     │
│  5. 结束清理 /tmp/                                     │
└─────────────────────────────────────────────────────────┘
                         │
                SSH 隧道 (-L)
                         ▼
┌─────────────────────────────────────────────────────────┐
│  远程服务器 (零安装、无痕)                               │
│                                                          │
│  /tmp/nanobot-xxx/  ← 临时，结束后删除                │
│    └── remote_server.py (WebSocket Server)             │
│                                                          │
│  tmux 会话 nanobot  ← 保持上下文                        │
└─────────────────────────────────────────────────────────┘
```

### 方案二：反向 WebSocket + tmux

> 远程主动连接 Gateway，适合无法接受入站连接的场景。

**使用场景：**
- 远程在 NAT 后面，无法接受连接
- 需要多个远程统一管理（团队场景）
- 配合 ngrok / Cloudflare Tunnel 使用

```
┌─────────────────────────────────────────────────────────┐
│  Gateway (NodeServer)                                   │
│                                                          │
│  1. 监听 WebSocket 端口 (如 18792)                    │
│  2. 等待远程主机连接                                    │
│  3. 接收命令 + 返回结果                                 │
└─────────────────────────────────────────────────────────┘
                         │
              WebSocket (反向连接)
                         │
┌─────────────────────────────────────────────────────────┐
│  远程服务器 (零安装、无痕)                               │
│                                                          │
│  /tmp/nanobot-xxx/  ← 临时，结束后删除                │
│    └── remote_server.py (WebSocket 客户端)             │
│                                                          │
│  1. SSH 进入远程 (本地→远程)                          │
│  2. 部署 remote_server.py                              │
│  3. 启动: uv run remote_server.py                      │
│     - 主动连接 Gateway WebSocket                      │
│     - 使用 tmux 保持会话                               │
│  4. 双向通信                                            │
│  5. 结束: rm -rf /tmp/nanobot-xxx/                    │
└─────────────────────────────────────────────────────────┘
```

### 两种方案对比

| | SSH 隧道 + WebSocket | 反向 WebSocket |
|---|---|---|
| **首次 SSH** | ✅ 需要 | ✅ 需要 |
| **后续连接** | 本地 → 远程 (隧道) | 远程 → 本地 |
| **本地端口** | 无需开放 | 需要开放 (或用 ngrok) |
| **远程需要** | SSH 开放 | 能访问外网 |
| **适用场景** | 个人使用 / 服务器 | NAT 后 / 多远程 / 团队 |

**性能方面：两者差别不大**，都是通过 WebSocket 通信。

**选择建议：**
- 个人使用 → SSH 隧道（简单，不需要本地开放端口）
- 多远程统一管理 → 反向 WebSocket

---

## 3. 核心特性

### 3.1 无需安装

```
远程只需要：
- bash ✅ (默认有)
- SSH  ✅ (本地需要)
- uv   ✅ (如无，curl 自动安装)
- tmux ✅ (用于会话保持)

不需要安装任何 nanobot 相关软件！
```

### 3.2 动态部署

```
第一次连接:
  │
  ├─ SSH 进入远程
  ├─ 创建 /tmp/nanobot-xxx/
  ├─ 复制 Python 脚本 (base64)
  └─ uv run remote_server.py
      │
      ▼
后续通信: WebSocket
      │
      ▼
结束时: rm -rf /tmp/nanobot-xxx/
```

### 3.3 会话保持

使用 tmux 保持远程上下文：

```
用户: "cd /project"
  → Gateway → WebSocket → tmux → 执行 cd
  → 返回结果

(10分钟后)

用户: "ls"
  → Gateway → 同一 WebSocket → 同一 tmux 会话
  → ls 在 /project 目录中执行！
```

### 3.4 零痕迹

```
会话结束:
  - 关闭 WebSocket
  - 杀死 tmux 会话
  - rm -rf /tmp/nanobot-xxx/

远程服务器: 没有任何痕迹留下 ✅
```

### 3.5 高性能

| 操作 | 延迟 |
|------|------|
| 首次连接 | ~200ms (可接受) |
| 后续命令 | ~5ms (几乎无感) |

原因：
- SSH 隧道只建立一次
- WebSocket 连接保持复用
- tmux 会话复用

---

## 4. 使用方式

### 4.1 用户指令

```
用户: "在 build-server 上分析 /app 项目"

用户: "连接到远程服务器 192.168.1.100"

用户: "在 server-A 上运行 pytest"
```

### 4.2 配置

```json
{
  "tools": {
    "exec": {
      "remote_hosts": {
        "build-server": "user@192.168.1.100"
      }
    }
  }
}
```

### 4.3 内部流程

```
用户输入
    │
    ▼
Gateway 判断: 需要远程执行？
    │
    ├─ 否 → 本地执行
    │
    └─ 是
          │
          ├─ 建立 SSH 隧道
          ├─ 部署 remote_server.py
          ├─ 启动 tmux 会话
          ├─ 通过 WebSocket 发送命令
          │
          └─ 返回结果
```

---

## 5. 示例

### 示例 1: 简单命令

```
用户: "在 build-server 上运行 ls /app"

Gateway:
  1. SSH 隧道建立 (~200ms)
  2. 部署 + 启动 nanobot-remote
  3. WebSocket: "ls /app"
  4. tmux: send-keys "ls /app"
  5. 捕获输出，返回

结果: 显示 /app 目录内容
```

### 示例 2: 保持上下文

```
用户: "cd /project && npm install"

Gateway → WebSocket → tmux:
  send-keys "cd /project"
  send-keys "npm install"
  capture-pane

用户: "npm test"  (10分钟后)

Gateway → 同一 WebSocket → 同一 tmux:
  send-keys "npm test"  ← 仍在 project 目录！
  capture-pane

结果: npm test 输出
```

### 示例 3: subagent 分析

```
用户: "派一个 subagent 分析 build-server 上的 /app 项目"

Gateway:
  1. subagent 启动
  2. 所有 exec 自动路由到远程:
     - find /app -name "*.py"
     - cat /app/main.py
     - cat /app/utils.py
     - ... (全部在远程执行)
  3. subagent 分析结果
  4. 返回给用户

结果: 完整的代码分析报告
```

---

## 6. 实现细节

### 6.1 remote_server.py (约 50 行)

```python
#!/usr/bin/env python3
"""nanobot-remote: 极简 WebSocket Server + tmux wrapper"""
import asyncio
import websockets
import json
import subprocess
import os

SESSION = "nanobot"
PORT = 8765

async def handler(ws):
    # 启动 tmux 会话
    subprocess.run(f"tmux new-session -d -s {SESSION}", shell=True)
    
    try:
        async for msg in ws:
            req = json.loads(msg)
            cmd = req["params"]["command"]
            
            # 发送到 tmux
            subprocess.run(f'tmux send-keys -t {SESSION} "{cmd}" Enter', shell=True)
            await asyncio.sleep(0.5)  # 等待执行
            
            # 获取输出
            result = subprocess.run(
                f"tmux capture-pane -t {SESSION} -p",
                shell=True, capture_output=True, text=True
            )
            
            # 返回结果
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {"stdout": result.stdout, "exitCode": 0}
            }))
    finally:
        # 清理
        subprocess.run(f"tmux kill-session -t {SESSION}", shell=True)

asyncio.run(websockets.serve(handler, "0.0.0.0", PORT))
```

### 6.2 简单实现示例 (connect/close)

> 以下是简化版本，完整实现见 Section 7。

```python
import asyncio
import websockets
import json
import base64

class RemoteHost:
    def __init__(self, ssh_host, remote_port=8765):
        self.ssh_host = ssh_host
        self.remote_port = remote_port
        self.local_port = 18790
        self.ws = None
    
    async def connect(self):
        # 1. 建立 SSH 隧道
        tunnel_cmd = f"ssh -N -L {self.local_port}:127.0.0.1:{self.remote_port} {self.ssh_host}"
        self.tunnel = await asyncio.create_subprocess_shell(
            tunnel_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(2)
        
        # 2. 部署 nanobot-remote (base64 编码传输)
        script = open("nanobot_node.py").read()
        encoded = base64.b64encode(script.encode()).decode()
        
        await self._ssh_exec(f"mkdir -p /tmp/nanobot-$$")
        await self._ssh_exec(f"echo {encoded} | base64 -d > /tmp/nanobot-$$/server.py")
        
        # 3. 启动
        await self._ssh_exec("cd /tmp/nanobot-$$ && uv run --with websockets server.py &")
        await asyncio.sleep(2)
        
        # 4. 连接 WebSocket
        self.ws = await websockets.connect(f"ws://127.0.0.1:{self.local_port}")
    
    async def exec(self, command):
        await self.ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "exec.run",
            "params": {"command": command}
        }))
        response = await self.ws.recv()
        return json.loads(response)["result"]["stdout"]
    
    async def close(self):
        if self.ws:
            await self.ws.close()
        await self._ssh_exec("rm -rf /tmp/nanobot-*")
        self.tunnel.terminate()
    
    async def _ssh_exec(self, cmd):
        result = await asyncio.create_subprocess_shell(
            f"ssh {self.ssh_host} {cmd}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await result.communicate()
```

### 6.3 Python 技术栈

| 技术 | 库 | 说明 |
|------|-----|------|
| WebSocket | `websockets` | 纯 Python，性能足够 |
| JSON | `json` (内置) | JSON-RPC 协议 |
| SSH | `asyncio.create_subprocess_shell` | SSH 隧道 |

---

## 7. Lifecycle: setup() 和 teardown()

> Section 6.2 是简化版本。这里是更完整的实现，包含错误处理、重连机制等。

### 7.1 核心方法

```python
class RemoteHost:
    def __init__(self, ssh_host):
        self.ssh_host = ssh_host
        self.tunnel = None
        self.ws = None
        self.session_id = None
    
    async def setup(self):
        """建立连接"""
        # 1. 生成唯一 session ID
        self.session_id = f"nanobot-{uuid.uuid4().hex[:8]}"
        
        # 2. 建立 SSH 隧道
        self.tunnel = await self._create_ssh_tunnel()
        
        # 3. 部署 nanobot-remote
        await self._deploy()
        
        # 4. 连接 WebSocket
        self.ws = await self._connect_websocket()
        
        # 5. 创建 tmux 会话
        await self._create_tmux_session()
        
        return self.session_id
    
    async def teardown(self):
        """清理资源"""
        try:
            # 1. 关闭 WebSocket
            if self.ws:
                await self.ws.close()
            
            # 2. 杀死 tmux 会话
            if self.session_id:
                await self._ssh_exec(f"tmux kill-session -t {self.session_id}")
            
            # 3. 清理远程临时文件
            if self.session_id:
                await self._ssh_exec(f"rm -rf /tmp/{self.session_id}")
            
        finally:
            # 4. 关闭 SSH 隧道
            if self.tunnel:
                self.tunnel.terminate()
```

### 7.2 使用方式

```python
# 方式 1: 上下文管理器
async with RemoteHost("user@server") as host:
    await host.exec("cd /project")
    result = await host.exec("pytest")
# 自动 teardown

# 方式 2: 手动管理
host = RemoteHost("user@server")
session_id = await host.setup()
try:
    result = await host.exec("ls")
finally:
    await host.teardown()
```

---

## 8. Robustness: 网络中断处理

### 8.1 场景分析

| 场景 | 影响 | 处理 |
|------|------|------|
| SSH 隧道断开 | 无法通信 | 检测 + 重连 |
| WebSocket 断开 | 无法通信 | 检测 + 重连 |
| tmux 进程崩溃 | 会话丢失 | 检测 + 重建 |
| 用户中断 (Ctrl+C) | 资源泄漏 | 捕获信号 + teardown |

### 8.2 完整错误处理

```python
class RemoteHost:
    async def setup(self, timeout=30):
        """完整设置：部署 + 启动 + 连接"""
        try:
            # 1. 生成唯一 session ID
            self.session_id = f"nanobot-{uuid.uuid4().hex[:8]}"
            
            # 2. 建立 SSH 隧道
            self.tunnel = await asyncio.wait_for(
                self._create_ssh_tunnel(),
                timeout=timeout
            )
            
            # 3. 部署 nanobot-remote (复制文件)
            await self._deploy()
            
            # 4. 启动 nanobot-remote
            await self._start_node()
            
            # 5. 连接 WebSocket
            self.ws = await asyncio.wait_for(
                websockets.connect(...),
                timeout=timeout
            )
            
            # 6. 创建 tmux 会话
            await self._create_tmux_session()
            
            self._running = True
            
        except asyncio.TimeoutError:
            await self.teardown()
            raise ConnectionError("连接超时")
    
    async def reconnect(self):
        """轻量级重连：无需重新部署
        
        远程保留：
        - tmux 会话 ✅
        - remote_server.py 进程 ✅
        - 工作目录、环境变量、运行中的进程 ✅
        
        本地重建：
        - SSH 隧道
        - WebSocket 连接
        """
        try:
            # 1. 重建 SSH 隧道
            self.tunnel = await self._create_ssh_tunnel()
            
            # 2. 重新连接 WebSocket
            self.ws = await websockets.connect(f"ws://127.0.0.1:{self.local_port}")
            
            # 完成！tmux 会话还在，工作状态都保留
            self._running = True
            print("重连成功")
            
        except Exception as e:
            # 如果轻量级重连失败，尝试完整重连
            print(f"轻量级重连失败: {e}，尝试完整重连...")
            await self.teardown()
            await self.setup()
    
    async def exec(self, command):
        """带重试的执行"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # 检查连接状态
                if not self._running or self.ws.closed:
                    await self.reconnect()  # 使用轻量级重连
                
                # 发送命令
                await self.ws.send(...)
                return await self.ws.recv()
                
            except websockets.exceptions.ConnectionClosed:
                await self.reconnect()
                continue
        
        raise ConnectionError("命令执行失败")
    
    async def teardown(self):
        """确保清理"""
        self._running = False
        
        # 清理顺序很重要
        cleanup_steps = [
            ("WebSocket", self._close_websocket),
            ("tmux", self._kill_tmux),
            ("temp files", self._cleanup_temp),
            ("SSH tunnel", self._close_tunnel),
        ]
        
        for name, cleanup in cleanup_steps:
            try:
                await cleanup()
            except Exception as e:
                logger.warning(f"清理 {name} 失败: {e}")
```

**setup() vs reconnect() 对比：**

| 操作 | setup() | reconnect() |
|------|---------|-------------|
| 生成 session ID | ✅ | ❌ (沿用) |
| 建立 SSH 隧道 | ✅ | ✅ |
| 部署文件 | ✅ | ❌ (远程有) |
| 启动进程 | ✅ | ❌ (远程有) |
| 连接 WebSocket | ✅ | ✅ |
| 创建 tmux | ✅ | ❌ (远程有) |
| **总步数** | 6 步 | 2 步 |
```

### 8.3 Signal 处理

```python
import signal

async def main():
    host = RemoteHost("user@server")
    
    # 捕获 Ctrl+C
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, 
            lambda: asyncio.create_task(host.teardown())
        )
    
    # 使用 host
    ...

# 或使用 TaskGroup (Python 3.11+)
async def main():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_agent())
        tg.create_task(monitor_connection())  # 监控连接健康
```

---

## 9. 与现有 nanobot tmux skill 的区别

### 现有 tmux skill

| 特性 | 说明 |
|------|------|
| **范围** | 本地 tmux（与 nanobot 同一台机器） |
| **远程使用** | 需要先 SSH 到远程，再手动操作 |
| **subagent** | ❌ 无法在远程使用 |
| **自动化** | 每次需要用户手动 SSH |

### Remote Host

| 特性 | 说明 |
|------|------|
| **范围** | 远程机器（通过 SSH 隧道） |
| **远程使用** | Gateway 自动建立连接 |
| **subagent** | ✅ subagent 可使用远程资源（文件、命令输出） |
| **自动化** | 完全自动化，用户无感知 |

### 核心区别

```
现有 tmux skill:
  用户 ──SSH──► 远程服务器 ──► tmux (手动操作)
                          ❌ subagent 不可用

Remote Host:
  用户 ──► Gateway ──► WebSocket ──► 远程 tmux (自动控制)
                                          ✓ subagent 可用！
```

---

## 10. 总结

### 特性汇总

| 特性 | 状态 |
|------|------|
| subagent 使用远程资源 | ✅ |
| 无需安装 | ✅ |
| 动态部署 | ✅ |
| 会话保持 | ✅ |
| 零痕迹 | ✅ |
| 高性能 | ✅ |
| 健壮性 (重连/清理) | ✅ |

---

## 11. Host 抽象架构

### 核心概念

将「本地」和「遠程」統一為「Host」抽象：

```
┌─────────────────────────────────────────────────────────────┐
│  nanobot                                                │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Host Abstraction (節點抽象)                       │   │
│  │                                                  │   │
│  │  ┌─────────────┐    ┌─────────────┐            │   │
│  │  │ Local Host │    │ Remote Host │            │   │
│  │  │             │    │             │            │   │
│  │  │ - tools/    │    │ - SSH      │            │   │
│  │  │ - skills/   │    │ - WebSocket│            │   │
│  │  │ - memory/  │    │ - tmux     │            │   │
│  │  │ - session/ │    │             │            │   │
│  │  └─────────────┘    └─────────────┘            │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Tools/Skills 的 Host 依賴

| Tool/Skill | Host 依賴 | 說明 |
|------------|-----------|------|
| **exec** | 可配置 | 需要訪問遠程代碼/執行命令 |
| **read_file** | 可配置 | 需要讀取遠程檔案 |
| **write_file** | 可配置 | 需要寫入遠程檔案 |
| **list_dir** | 可配置 | 需要列出遠程目錄 |
| **weather** | ❌ Local | 只需要網絡 |
| **summarize** | ❌ Local | 只需要網絡 |
| **github** | ⚠️ 可選 | 可本地可遠程 |
| **cron** | ❌ Local | 假設本地 |
| **memory** | ❌ Local | 假設本地 |
| **session** | ❌ Local | 假設本地 |

### 配置方式

```json
{
  "hosts": {
    "local": {
      "type": "local"
    },
    "build-server": {
      "type": "remote",
      "ssh": "user@192.168.1.100"
    },
    "prod-server": {
      "type": "remote",
      "ssh": "user@prod.example.com"
    }
  }
}
```

> 工具通过 `host` 参数动态指定目标主机，无需在配置中静态绑定。

### 动态指定

```
用户: "在 build-server 上运行 pytest"
→ exec(command="pytest", host="build-server")

用户: "读取 prod-server 上的 /app/config.py"
→ read_file(path="/app/config.py", host="prod-server")

用户: "今天天气如何" (默认本地)
→ weather() → 自动使用 local 主机
```
```

### 執行流程

```
┌─────────────────────────────────────────────────────────────┐
│  Tool Execution Flow                                       │
│                                                              │
│  Tool Call: read_file(path="/project/main.py")            │
│      │                                                      │
│      ▼                                                      │
│  檢查配置: read_file.host = ?                              │
│      │                                                      │
│      ├─ "local" → 本地執行                                 │
│      │                                                      │
│      └─ "build-server" → 通過 Remote Host 執行              │
│           │                                                 │
│           ├─ SSH 隧道建立 (如未建立)                        │
│           ├─ WebSocket 發送命令                             │
│           └─ 返回結果                                       │
└─────────────────────────────────────────────────────────────┘
```

---

### 11. 總結

| 特性 | 狀態 |
|------|------|
| subagent 使用遠程資源 | ✅ |
| 無需安裝 | ✅ |
| 動態部署 | ✅ |
| 會話保持 | ✅ |
| 零痕跡 | ✅ |
| 高性能 | ✅ |
| 健壯性 (重連/清理) | ✅ |
| Host 抽象架構 | ✅ |
| Tools/Skills Host 依賴 | ✅ |

---

### 架構優勢

```
┌────────────────────────────────────────────┐
│  零安裝 │ 零痕跡 │ 高性能 │ 會話保持      │
│              Host 抽象架構                │
└────────────────────────────────────────────┘
```

### 未來擴展

- 多遠程機器管理
- 遠程文件瀏覽器
- 遠程瀏覽器自動化

---

## 12. 借鑒第三方 Fork 實現

> 參考: [EisonMe/nanobot#a1b05e9](https://github.com/EisonMe/nanobot/commit/a1b05e962a37ae89b3a5381cf70691642f466e5b)

### 12.1 反向 WebSocket 連接

#### 問題

我們之前用 SSH 隧道：
```
Gateway ← SSH 隧道 ← Remote
```

但 SSH 隧道需要本地先發起連接，且需要維護隧道。

#### 解決方案：反向 WebSocket

```
Remote (NodeClient) ──────► Gateway (NodeServer)
     │
     │ 主動連接 WebSocket
     │
     ▼
建立雙向通信
```

**為什麼更簡單？**
| 方面 | SSH 隧道 | 反向 WebSocket |
|------|----------|----------------|
| 連接方向 | 本地 → 遠程 | 遠程 → 本地 |
| NAT 穿透 | 需要端口轉發 | 主動連接，無需配置 |
| 維護 | 需要保持隧道 | WebSocket 自動維護 |
| 防火牆 | 需要開放入站端口 | 只需要出站 WebSocket |

```python
# 遠程 NodeClient 主動連接
async def connect():
    ws = await websockets.connect("ws://gateway:18792")
    await ws.send({"type": "auth", "token": "...", "name": "remote-1"})
```

---

### 12.2 Token 認證

#### SSH 已經很安全，為什麼還要 Token？

```
SSH: 網絡傳輸安全 (TLS/SSH)
Token: 應用層安全
```

| 層次 | 保護 | 用途 |
|------|------|------|
| **SSH** | 傳輸加密 | 防止網絡竊聽 |
| **Token** | 應用認證 | 防止未授權訪問 |

**Token 認證的價值：**

1. **多租戶隔離** - 不同用戶/節點用不同 Token
2. **精細控制** - 可以撤銷單個 Token而不影響其他
3. **審計追蹤** - 記錄誰在什麼時間連接
4. **簡單部署** - 不需要 SSH Key 管理

```python
# Gateway 端驗證
async def handle_connection(ws):
    auth_msg = await ws.recv()
    auth = json.loads(auth_msg)
    
    if auth["token"] != config.token:
        await ws.send({"type": "error", "message": "Invalid token"})
        return
    
    # 認證成功
    await ws.send({"type": "auth_success"})
```

---

### 12.3 NodeServer 架構 vs 單文件

#### 單文件方案的問題

```
remote_server.py (單文件)
  │
  ├── WebSocket Server
  ├── 命令執行
  └── 連接管理
  │
  ❌ 所有邏輯混在一起
  ❌ 難以擴展
  ❌ 難以測試
```

#### NodeServer 架構的優勢

```
NodeServer (模塊化)
  │
  ├── ConnectionManager  (連接管理)
  ├── AuthManager      (認證)
  ├── ExecManager      (命令執行)
  └── NodeRegistry    (節點註冊)
  │
  ✅ 職責分離
  ✅ 易於測試
  ✅ 易於擴展
```

**但實際上：**

對於我們的「動態部署」場景，單文件確實更簡單！

| 方案 | 適用場景 |
|------|----------|
| **單文件** | 動態部署、快速部署 |
| **NodeServer 架構** | 官方 nanobot、需要長期運行的場景 |

**可以借鑒的部分：**
- Token 認證機制
- NodesTool (管理多個節點)

---

### 12.4 NodesTool: 多節點管理

#### 功能設計

```python
class NodesTool:
    """管理多個遠程節點"""
    
    @property
    def name(self) -> str:
        return "hosts"
    
    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove", "status", "exec"]
                },
                "name": {"type": "string"},  # 節點名稱
                "ssh": {"type": "string"},    # SSH 地址
                "command": {"type": "string"}, # 執行命令
            },
            "required": ["action"]
        }
```

#### Actions

| Action | 功能 | 示例 |
|--------|------|------|
| **list** | 列出所有連接的節點 | `hosts action="list"` |
| **add** | 添加新節點 | `hosts action="add" name="build-server" ssh="user@192.168.1.100"` |
| **remove** | 移除節點 | `hosts action="remove" name="build-server"` |
| **status** | 查看節點狀態 | `hosts action="status" name="build-server"` |
| **exec** | 在指定節點執行命令 | `hosts action="exec" name="build-server" command="ls /app"` |

#### 使用示例

```
用戶: "列出所有連接的節點"
→ hosts action="list"
← 連接的節點 (2):
   - build-server
   - test-machine

用戶: "在 build-server 上運行 pytest"
→ hosts action="exec" name="build-server" command="cd /app && pytest"
← pytest 結果: 15 passed, 2 failed

用戶: "添加新節點 production"
→ hosts action="add" name="production" ssh="user@prod-server"
✓ 節點已添加

用戶: "移除 test-machine"
→ hosts action="remove" name="test-machine"
✓ 節點已移除
```

#### 實現

```python
async def execute(self, action, name=None, ssh=None, command=None):
    if action == "list":
        return self._list_nodes()
    elif action == "add":
        return await self._add_node(name, ssh)
    elif action == "remove":
        return await self._remove_node(name)
    elif action == "status":
        return await self._node_status(name)
    elif action == "exec":
        return await self._exec_on_node(name, command)
```

---

### 12.5 借鑒總結

| 我們借鑒 | 來自 Fork | 說明 |
|----------|-----------|------|
| 反向 WebSocket | ✅ | 簡化連接方式 |
| Token 認證 | ✅ | 應用層安全 |
| NodesTool | ✅ | 多節點管理 |
| 動態部署 | ❌ | 我們獨特優勢 |
| tmux 會話 | ❌ | 我們獨特優勢 |
| 智能工具分流 | ❌ | 我們獨特優勢 |

---

### 最終架構

```
┌─────────────────────────────────────────────────────────────┐
│  Gateway                                                  │
│                                                           │
│  ┌─────────────────────────────────────────────────┐   │
│  │ NodeServer                                          │   │
│  │   - WebSocket Server (反向連接)                   │   │
│  │   - Token 認證                                    │   │
│  │   - NodesTool (多節點管理)                       │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           │
                     WebSocket
                           │
    ┌────────────────────────┼────────────────────────┐
    │                        │                        │
    ▼                        ▼                        ▼
┌──────────┐          ┌──────────┐          ┌──────────┐
│ Host A   │          │ Host B   │          │ Host C   │
│ (tmux)   │          │ (tmux)   │          │ (tmux)   │
└──────────┘          └──────────┘          └──────────┘

動態部署: SSH → /tmp/nanobot-remote/ → uv run
零痕跡: 結束後 rm -rf /tmp/
```

---

### 12.6 設計澄清

#### Q: 远程需要安装吗？

**A: 不需要！**

```
SSH 进去 → 部署脚本 → uv run → 连接 Gateway
```

#### Q: 连接方向？

**A: 远程主动连接 Gateway**

```
远程 (remote_server.py)
    │
    │ 主动连接 WebSocket
    │ + Token 认证
    ▼
Gateway (NodeServer)
    │
    │ 监听 0.0.0.0:18792
    ▼
建立双向通信
```

#### Q: NodeServer 需要长期运行？

**A: 是的，作为 Gateway 的一部分**

```
Gateway 机器:
    │
    ├─ nanobot gateway (一直运行)
    │
    └─ NodeServer (一直运行)
         │
         │ 监听 WebSocket 端口
         │ 等待远程主机连接
         ▼
    远程主机连接...
```

#### Q: 远程文件可以是单文件吗？

**A: 可以，简单更好！**

```
远程: remote_server.py (单文件)
    - WebSocket 客户端
    - 执行命令
    - 返回结果

Gateway: NodeServer (模块化)
    - 连接管理
    - Token 认证
    - 主机注册
```

---

### 12.7 简化后的完整流程

```
用户: "连接到 build-server 分析项目"

Gateway:
  1. SSH 到 build-server
  2. 部署 remote_server.py → /tmp/nanobot-xxx/
  3. 启动: uv run remote_server.py --server ws://gateway:18792 --token xxx
  4. 远程主机主动连接 Gateway WebSocket
  5. 通过 WebSocket 发送命令
  6. 结束: 远程 cleanup /tmp/

完美结合:
  ✅ 无需预装 (动态部署)
  ✅ 反向连接 (远端主动)
  ✅ Token 认证 (安全)
  ✅ tmux 会话 (可选)
```

---

## 13. 实现: "run X on server" 如何工作

### 13.1 核心问题

当用户说 "run X on server" 时，nanobot 需要：
1. 知道有哪些 remote host 可用
2. 让 LLM 理解可以使用 remote host
3. 将工具调用正确路由到 remote 执行

### 13.2 Host Registry (主机注册表)

存储 remote host 配置：

```python
# hosts.json 或内存中
{
  "prod-server": {
    "host": "prod.example.com",
    "user": "admin",
    "auth": "ssh_key",
    "status": "connected"  # 或 "disconnected"
  },
  "build-server": { ... }
}
```

**LLM 感知方式：** 在 system prompt 中包含可用主机：

```
## Remote Hosts

You have access to remote servers:
- prod-server (connected)
- build-server (connected)

Use "on <host>" syntax to run commands on remote.
```

### 13.3 Host-Aware Tools (主机感知工具)

扩展现有工具，添加 `host` 参数：

```python
@tool
def exec(command: str, host: str = "local"):
    """Execute shell command.
    
    Args:
        command: shell command to run
        host: target host (default: local). Use "prod-server" or "build-server" for remote.
    """
    if host == "local":
        return local_exec(command)
    else:
        return remote_exec(host, command)  # 通过 WebSocket
```

同样适用于 `read_file`, `write_file`, `grep` 等。

### 13.4 Natural Language Parsing (自然语言解析)

**两种方式：**

**方式 A: 显式语法** (简单)
```
User: "run pytest on prod-server"
→ LLM 调用: exec(command="pytest", host="prod-server")
```

**方式 B: 上下文感知** (更智能)
```
User: "run pytest"  (如果 prod-server 是当前上下文)
→ LLM 调用: exec(command="pytest", host="prod-server")
```

LLM 从对话上下文学习哪个 host 是"活跃的"。

### 13.5 System Prompt 增强

在 system prompt 中添加：

```
## Remote Hosts

You have access to remote servers:
- prod-server (connected)
- build-server (connected)

Tools can run on remote by specifying host parameter:
- exec(command="ls -la", host="prod-server")
- read_file(path="/etc/nginx.conf", host="prod-server")

If user mentions a server name, use that as host.
If user says "on <server>", use that as host.
```

### 13.6 Tool Routing (工具路由)

```python
async def exec(command: str, host: str = "local"):
    if host == "local":
        return await local_exec(command)
    
    # 获取远程连接
    connection = connections.get(host)
    if not connection:
        # 自动连接（如需要）
        connection = await connect_to_node(host)
    
    # 通过 WebSocket 发送到远程 agent
    result = await connection.execute(command)
    return result
```

### 13.7 示例流程

```
用户: "run pytest on build-server"

1. LLM 看到 "build-server" → 知道是 remote host
2. LLM 调用: exec(command="pytest", host="build-server")
3. Tool 检查: host != "local" → 路由到 remote
4. Remote agent 执行: subprocess.run("pytest")
5. 返回结果给用户
```

```
用户: "read main.py on prod-server"

1. LLM 调用: read_file(path="main.py", host="prod-server")
2. Tool 路由到 remote
3. Remote agent: 读取文件，返回内容
4. 用户获得文件内容，如同本地读取
```

### 13.8 关键设计决策

| 决策 | 选项 | 推荐 |
|------|------|------|
| **工具设计** | 分离工具 (exec_remote) vs 统一 (exec + host 参数) | 统一 — LLM 更容易学习 |
| **Host 指定** | 显式 ("on server") vs 上下文 | 两者都支持 — 显式优先，上下文作为后备 |
| **连接时机** | 懒连接 (首次命令时) vs 预连接 (添加时) | 懒连接 — 添加主机更快 |
| **多主机命令** | 顺序执行 vs 并行执行 | 并行 — 独立命令可并行 |

### 13.9 优先级: 先实现什么

1. **Host 配置存储** — 添加主机定义
2. **Basic exec + host 参数** — 最简单的远程命令
3. **System prompt 更新** — 让 LLM 感知
4. **连接池** — 管理远程连接
5. **更多 host-aware 工具** — read_file, write_file 等

---

## 14. 未来增强功能

### 14.1 安全增强

| 项目 | 说明 |
|------|------|
| **目录权限** | `/tmp/nanobot-xxx/` 设置 `chmod 700`，防止其他用户读取 |
| **命令注入防护** | 验证/清理用户输入，防止命令注入 |
| **认证方式** | SSH key vs password 支持 |
| **Token 认证** | 应用层 Token 验证（参考 Section 12.2） |

### 14.2 长时间运行命令

| 项目 | 说明 |
|------|------|
| **Streaming 输出** | 实时返回命令输出（如 `tail -f`） |
| **超时控制** | 可配置命令超时时间 |
| **命令取消** | 支持中断正在运行的命令 |
| **后台任务** | 支持 `nohup` / `&` 模式 |

```
用户: "在 build-server 上运行 npm run dev"
→ nanobot: "已启动，后台运行中..."
→ 用户可以继续其他操作

用户: "查看 dev server 日志"
→ nanobot: 返回实时日志输出
```

### 14.3 大文件处理

| 方案 | 说明 |
|------|------|
| **分块传输** | 大文件分块读取/写入 |
| **scp/rsync** | 对于大文件，使用 scp/rsync 方式传输 |
| **流式处理** | 边下载边处理（如解压、搜索） |

```
用户: "下载 build-server 上的 1GB 日志文件"
→ 使用 scp 传输
→ 进度实时显示
```

### 14.4 无 tmux 方案 (bash -i)

如果远程没有 tmux，可以尝试使用交互式 bash：

```python
# 使用 pseudo-terminal + interactive shell
subprocess.run([
    "ssh", host,
    "bash -i -c 'command'"
])
```

**限制：**
- 无法保持会话状态
- 每次命令新建 shell
- 适合简单命令场景

> **注：** 此方案作为 fallback，当 tmux 不可用时使用
```
