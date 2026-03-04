# Remote Host — Feasibility Analysis

After reviewing the nanobot codebase, here's my assessment:

---

## Current Architecture (Relevant Parts)

```
┌─────────────────────────────────────────────────────────────┐
│  nanobot/agent/                                              │
│                                                             │
│  loop.py        ← AgentLoop (main orchestrator)            │
│  context.py     ← ContextBuilder (prompts)                 │
│  subagent.py    ← SubagentManager (background tasks)       │
│                                                             │
│  tools/                                                   │
│  ├── shell.py        ← ExecTool (shell commands)           │
│  ├── filesystem.py   ← ReadFileTool, WriteFileTool, etc.   │
│  └── registry.py     ← ToolRegistry (tool management)       │
└─────────────────────────────────────────────────────────────┘
```

---

## Dependencies Already Available

| Dependency | Status | Usage |
|------------|--------|-------|
| `websockets` / `websocket-client` | ✅ Already in pyproject.toml | WebSocket server/client |
| `python-socketio` | ✅ Already in pyproject.toml | Socket.IO support |
| `asyncssh` | ⚠️ Not present | SSH connectivity (need to add) |

---

## Minimal Implementation Plan

### 1. New file: `nanobot/agent/hosts.py` (~120 lines)

```python
class Host(ABC):
    """Base host class."""
    @abstractmethod
    async def exec(self, command: str, **kwargs) -> str: ...
    
    @abstractmethod
    async def read_file(self, path: str) -> str: ...
    
    # ... other tool proxies

class LocalNode(Host):
    """Current behavior - direct tool execution."""
    # Wraps existing tools directly

class RemoteHost(Host):
    """Proxies tool calls over WebSocket to remote."""
    def __init__(self, host: str, ssh_config: dict): ...
    async def connect(self): ...  # SSH + deploy + WebSocket
    async def exec(self, command: str, **kwargs) -> str: ...  # proxy to remote
    async def disconnect(self): ...  # cleanup
```

### 2. Modify `nanobot/agent/loop.py` (~30 lines)

- Add `_nodes: dict[str, Host]` and `_current_node: str`
- Add methods: `add_node()`, `switch_node()`, `get_current_node()`
- When executing tools, route through current host

### 3. Remote script: `remote_server.py` (~50 lines)

```python
# Deployed to remote via SSH, runs in /tmp/
async def main():
    # WebSocket server that:
    # - Receives commands (exec, read_file, etc.)
    # - Executes locally
    # - Returns results
```

---

## Code Estimate

| Component | Lines |
|-----------|-------|
| `hosts.py` | ~120 |
| `loop.py` changes | ~30 |
| `remote_server.py` | ~50 |
| Config/schema | ~20 |
| **Total** | **~220 lines** |

---

## Why This Is Minimal

1. **No tool changes** — existing tools (ExecTool, ReadFileTool) stay as-is
2. **No rewrite** — just adds a routing layer
3. **WebSocket already in deps** — no new heavy dependencies
4. **Incremental** — can start with just `exec` remote, add more later

---

## MVP Scope (for even less)

Start with just:
1. `remote_exec` — run commands on remote server
2. `remote_read` — read files from remote

Skip for MVP:
- Persistent sessions (just one-off commands initially)
- Full tool coverage (just exec + read to start)
- Multi-host management (just one remote at a time)

**MVP: ~100 lines total**
