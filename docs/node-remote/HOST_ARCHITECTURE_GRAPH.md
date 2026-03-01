# Host / Remote 架构关系图（Mermaid）

> 目标：帮助快速理解 `HostManager`、`HostsTool`、`ExecTool`、文件类工具、Backend Router、Remote 运行时之间的关系与调用路径。

## 1) 静态关系（类/组件依赖）

```mermaid
classDiagram
    direction LR

    class AgentLoop {
      +host_manager: HostManager
      +backend_router: ExecutionBackendRouter
      +_register_default_tools()
    }

    class ToolRegistry {
      +register(tool)
      +execute(name, params)
    }

    class HostsTool {
      +name = "hosts"
      +execute(action,...)
      -_list_hosts()
      -_add_host()
      -_connect_host()
      -_exec_command()
    }

    class ExecTool {
      +name = "exec"
      +execute(command, working_dir, host)
    }

    class ReadFileTool {
      +execute(path, host)
    }
    class WriteFileTool {
      +execute(path, content, host)
    }
    class EditFileTool {
      +execute(path, old_text, new_text, host)
    }
    class ListDirTool {
      +execute(path, host)
    }
    class CompareTool {
      +execute(local_path, remote_path, host)
    }

    class ExecutionBackendRouter {
      +resolve(host) ExecutionBackend
    }

    class ExecutionBackend {
      <<interface>>
      +exec()
      +read_file()
      +write_file()
      +edit_file()
      +list_dir()
    }

    class LocalExecutionBackend
    class RemoteExecutionBackend

    class HostManager {
      +add_host()
      +connect()
      +get_or_connect()
      +disconnect()
      +list_hosts()
    }

    class HostsConfig {
      +load()
      +save()
      +add_host()
      +get_host()
      +list_hosts()
    }

    class RemoteHost {
      +setup()
      +teardown()
      +exec()
      +read_file()
      +write_file()
      +edit_file()
      +list_dir()
      -_rpc()
    }

    class RemoteServer {
      <<remote/remote_server.py>>
      +WebSocket handlers
      +exec/read_file/write_file/edit_file/list_dir
    }

    AgentLoop --> ToolRegistry : owns
    AgentLoop --> HostManager : owns
    AgentLoop --> ExecutionBackendRouter : owns

    AgentLoop --> HostsTool : register
    AgentLoop --> ExecTool : register
    AgentLoop --> ReadFileTool : register
    AgentLoop --> WriteFileTool : register
    AgentLoop --> EditFileTool : register
    AgentLoop --> ListDirTool : register
    AgentLoop --> CompareTool : register

    HostsTool --> HostManager : direct lifecycle ops

    ExecTool --> ExecutionBackendRouter : resolve(host)
    ReadFileTool --> ExecutionBackendRouter : resolve(host)
    WriteFileTool --> ExecutionBackendRouter : resolve(host)
    EditFileTool --> ExecutionBackendRouter : resolve(host)
    ListDirTool --> ExecutionBackendRouter : resolve(host)
    CompareTool --> ExecutionBackendRouter : resolve(local+remote)

    ExecutionBackendRouter --> LocalExecutionBackend : host is empty
    ExecutionBackendRouter --> HostManager : host provided
    HostManager --> RemoteHost : get_or_connect(host)
    ExecutionBackendRouter --> RemoteExecutionBackend : wrap(RemoteHost)

    LocalExecutionBackend ..|> ExecutionBackend
    RemoteExecutionBackend ..|> ExecutionBackend

    RemoteExecutionBackend --> RemoteHost : delegate RPC calls
    HostManager --> HostsConfig : persistence
    RemoteHost --> RemoteServer : WebSocket RPC over SSH tunnel
```

---

## 2) 动态流程 A：`exec command="..." host="myserver"`

```mermaid
sequenceDiagram
    participant U as User
    participant LLM as LLM
    participant TR as ToolRegistry
    participant ET as ExecTool
    participant BR as ExecutionBackendRouter
    participant HM as HostManager
    participant RH as RemoteHost
    participant RS as remote_server.py

    U->>LLM: "on myserver run ls -la"
    LLM->>TR: execute("exec", {command, host})
    TR->>ET: ExecTool.execute(...)
    ET->>BR: resolve("myserver")
    BR->>HM: get_or_connect("myserver")
    HM->>RH: setup() (if not connected)
    RH-->>HM: connected
    BR-->>ET: RemoteExecutionBackend
    ET->>RH: exec(command)
    RH->>RS: WS {type:"exec", command:"..."}
    RS-->>RH: {type:"result", success, output, exit_code}
    RH-->>ET: result dict
    ET-->>TR: formatted text
    TR-->>LLM: tool result
```

---

## 3) 动态流程 B：`read_file path="..." host="myserver"`

```mermaid
sequenceDiagram
    participant TR as ToolRegistry
    participant RFT as ReadFileTool
    participant BR as ExecutionBackendRouter
    participant REB as RemoteExecutionBackend
    participant RH as RemoteHost
    participant RS as remote_server.py

    TR->>RFT: execute(path, host)
    RFT->>BR: resolve(host)
    BR-->>RFT: RemoteExecutionBackend
    RFT->>REB: read_file(path)
    REB->>RH: read_file(path)
    RH->>RS: WS {type:"read_file", path}
    RS-->>RH: {type:"result", success, content/error}
    RH-->>REB: result
    REB-->>RFT: result
    RFT-->>TR: content / error text
```

---

## 4) `hosts` 工具与其他工具的职责边界

- `HostsTool`：**主机生命周期管理入口**（add/connect/disconnect/status/list/exec）。
- `ExecTool` / `ReadFileTool` / `WriteFileTool` / `EditFileTool` / `ListDirTool` / `CompareTool`：**业务工具**，通过 `ExecutionBackendRouter` 统一选择本地或远程后端。
- `HostManager`：**连接生命周期**（连接池、建立/断开连接），不做业务拼装。
- `RemoteHost` + `remote_server.py`：**远程 RPC 通道**与远端执行实现。

---

## 5) 一句话心智模型

- `hosts` 负责"**我要连哪台机器**"。
- `backend_router` 负责"**这次操作走本地还是远程**"。
- 具体工具负责"**我要做什么操作**"（exec/read/write/edit/list/compare）。

---

## 6) 动态流程 C：连接管理 — `connect()` vs `get_or_connect()`

### connect()：用户主动连接（ping 验证）

```mermaid
sequenceDiagram
    participant U as User
    participant LLM as LLM
    participant HT as HostsTool
    participant HM as HostManager
    participant RH as RemoteHost
    participant RS as remote_server.py

    U->>LLM: hosts action="connect" name="myserver"
    LLM->>HT: execute({action:"connect", name:"myserver"})
    HT->>HM: connect("myserver")

    alt 内存有 host
        HM->>RH: ping()
        alt ping 成功
            RH-->>HM: pong ✓
            HM-->>HT: "✓ Already connected"
        else ping 失败
            RH-->>HM: timeout ✗
            HM->>RH: disconnect() + teardown
            HM->>RH: resume or full deploy
            RH->>RS: setup/reconnect
            RS-->>RH: authenticated
            HM-->>HT: "✓ Connected (new session)"
        end
    else 内存没有
        HM->>RH: _try_resume() or setup()
        RH->>RS: connect
        RS-->>RH: authenticated
        HM-->>HT: "✓ Connected"
    end
```

### get_or_connect()：隐式连接（exec/router，无 ping）

```mermaid
sequenceDiagram
    participant U as User
    participant LLM as LLM
    participant RT as Router
    participant HM as HostManager
    participant RH as RemoteHost
    participant RS as remote_server.py

    U->>LLM: exec command="pwd" host="myserver"
    LLM->>RT: execute("exec", {command:"pwd", host:"myserver"})
    RT->>HM: get_or_connect("myserver")

    alt 内存有 host
        HM-->>RT: 直接返回（不 ping，信任 auto-heal）
    else 内存没有
        HM->>RH: _try_resume() or setup()
        RH-->>HM: connected
        HM-->>RT: RemoteHost
    end

    RT->>RH: _rpc({type:"exec", command:"pwd"})
    alt transport 正常
        RH->>RS: WebSocket 消息
        RS-->>RH: 结果
    else transport 断
        RH->>RH: auto-heal (_recover_transport)
        alt SSH 失败
            RH-->>RT: "Network unreachable: SSH tunnel failed"
        else WS 失败
            RH-->>RT: "Remote server not responding: WebSocket failed"
        else 恢复成功
            RH->>RS: 重试 WebSocket 消息
            RS-->>RH: 结果
        end
    end
```

> **关键区别**：`connect()` 主动 ping 验证 → 确保返回可用连接。`get_or_connect()` 不 ping → 信任 `_rpc()` auto-heal 处理传输问题。exec 不需要先 connect。

---

## 7) `remote_server.py` 内部结构图

```mermaid
flowchart TD
    A[WebSocket Connection] --> B[Auth Handshake]
    B --> C{msg_type}

    C -->|exec/execute| D[CommandExecutor.exec]
    D --> D1{tmux enabled?}
    D1 -->|yes| D2[TmuxSession.send_and_capture]
    D2 --> D3[marker parse + exit_code]
    D1 -->|no| D4[SimpleExecutor.execute]

    C -->|read_file| E[FileService.read_file]
    C -->|write_file| F[FileService.write_file]
    C -->|edit_file| G[FileService.edit_file]
    C -->|list_dir| H[FileService.list_dir]

    C -->|ping| I[send pong]
    C -->|shutdown| J[send shutdown_ack + stop_event.set]
    C -->|close| K[break loop]

    D3 --> R[send result]
    D4 --> R
    E --> R
    F --> R
    G --> R
    H --> R
    I --> R
    J --> R
    K --> Z[cleanup executor/tmux]
```

要点：
- `exec` 路径走 `CommandExecutor`，并在 tmux 模式下通过 marker 精确提取输出。
- 文件操作走 `FileService`，是结构化 RPC，不再依赖 shell 拼接。
- `shutdown` 会触发 `stop_event`，让服务端优雅退出。

---

## 8) `remote_server.py` 内部类关系图（更细粒度）

```mermaid
classDiagram
    direction LR

    class TmuxSession {
      +create()
      +send_and_capture(command)
      +destroy()
      -_capture_raw()
      -_parse_markers()
    }

    class SimpleExecutor {
      +execute(command)
    }

    class CommandExecutor {
      -use_tmux: bool
      -tmux: TmuxSession?
      +exec(command)
      -_execute_tmux(command)
      -_execute_simple(command)
      +cleanup()
    }

    class FileService {
      <<static>>
      +read_file(path)
      +write_file(path, content)
      +edit_file(path, old_text, new_text)
      +list_dir(path)
    }

    class ConnectionHandler {
      <<handle_connection()>>
      +auth
      +message loop
      +dispatch by msg_type
    }

    class ServerMain {
      <<main()>>
      +parse args
      +load config
      +start websockets.serve
      +wait stop_event
    }

    CommandExecutor --> TmuxSession : use when tmux enabled
    CommandExecutor --> SimpleExecutor : use when tmux disabled
    ConnectionHandler --> CommandExecutor : exec/execute
    ConnectionHandler --> FileService : read/write/edit/list
    ServerMain --> ConnectionHandler : create per connection
```

### 类协作要点

- `CommandExecutor` 是命令执行门面：
  - tmux 开启 → 委托 `TmuxSession`（marker 捕获 + exit code）
  - tmux 关闭 → 委托 `SimpleExecutor`
- `FileService` 是文件 RPC 处理器（纯静态方法），与 tmux 无关。
- `handle_connection()` 是协议路由层：认证后按 `msg_type` 分发给 `CommandExecutor` 或 `FileService`。
- `main()` 负责服务生命周期（启动、信号、stop_event）。

---

## 9) `RemoteHost` ↔ `remote_server.py` 协议交互图

```mermaid
sequenceDiagram
    participant RH as RemoteHost (local)
    participant SSH as SSH Tunnel
    participant WS as WebSocket
    participant RS as remote_server.py (remote)

    RH->>SSH: create -L local_port:127.0.0.1:remote_port
    RH->>RS: deploy.sh (upload + start remote_server.py)
    RH->>WS: connect ws://127.0.0.1:local_port
    RH->>RS: auth {token}
    RS-->>RH: {type:"authenticated"}

    rect rgb(240,248,255)
    note over RH,RS: RPC: exec
    RH->>RS: {type:"exec", command}
    RS-->>RH: {type:"result", success, output, error, exit_code}
    end

    rect rgb(245,255,245)
    note over RH,RS: RPC: file operations
    RH->>RS: {type:"read_file", path}
    RS-->>RH: {type:"result", success, content/error}

    RH->>RS: {type:"write_file", path, content}
    RS-->>RH: {type:"result", success, bytes/error}

    RH->>RS: {type:"edit_file", path, old_text, new_text}
    RS-->>RH: {type:"result", success, path/error}

    RH->>RS: {type:"list_dir", path}
    RS-->>RH: {type:"result", success, entries/error}
    end

    RH->>RS: {type:"shutdown"}
    RS-->>RH: {type:"shutdown_ack"}
    RH->>SSH: close tunnel
```

要点：
- `RemoteHost._rpc()` 是所有远程操作的统一入口（exec + 文件 RPC）。
- `remote_server.py` 负责协议分发，`RemoteHost` 负责连接生命周期与调用封装。
- `request_id` 用于幂等去重：同一个请求重试不会重复执行副作用命令。

---

## 10) 自动自愈与幂等策略（当前实现）

- 自动自愈：
  - 当 RPC 遇到传输层错误（SSH/WS 中断）时，`RemoteHost` 会尝试 **transport-only recovery**：
    1. 关闭旧 websocket/tunnel 句柄
    2. 重新建立 SSH tunnel
    3. 重新连接 WebSocket
    4. 重新认证
  - **不会**隐式 redeploy / 重建 session（避免用户 surprise）。

- 幂等去重：
  - 客户端每个 RPC 带 `request_id`。
  - 服务端维护 request cache + in-flight 表：
    - 已完成同 ID：直接返回缓存结果
    - 执行中同 ID：等待同一个 future 结果
    - 同 ID 但 payload 不同：返回错误

- 效果：
  - 网络瞬断时，用户再次发命令通常可无感恢复。
  - 断线重试同一请求不会导致重复写文件/重复执行副作用命令。

---

## 11) 从架构图跳转到"真实 LLM payload"样例

为方便 PR reviewer 将"架构设计"与"LLM 实际看到的输入"对应起来，本分支提供了真实运行时捕获（脱敏）样例：

- `docs/node-remote/PROVIDER_CHAT_PAYLOAD_SAMPLE.json`

建议阅读顺序：
1. 先看本文件的类图/时序图（理解组件关系与调用路径）
2. 再看 `PROVIDER_CHAT_PAYLOAD_SAMPLE.json`（验证 `messages + tools` 的真实形态）

重点关注样例中的：
- `tools[].function.name/description/parameters`（尤其 `host` 参数）
- `hosts` 工具动作 schema（生命周期管理）
- `exec/read_file/write_file/edit_file/list_dir` 在同一工具层统一支持远程
