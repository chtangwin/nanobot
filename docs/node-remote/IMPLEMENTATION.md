# Remote Node Implementation Notes

> Technical details of the remote node implementation

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Gateway (Local)                                            │
│                                                             │
│  nanobot/                                                   │
│  ├── nodes/                                                 │
│  │   ├── config.py      - Node configuration management    │
│  │   ├── connection.py  - RemoteNode (SSH + WebSocket)     │
│  │   └── manager.py     - NodeManager (multi-node)         │
│  ├── agent/tools/                                           │
│  │   ├── nodes.py       - NodesTool (user interface)       │
│  │   ├── shell.py       - exec with node parameter         │
│  │   └── filesystem.py  - read/write with node parameter   │
│  └── config/                                                │
│      └── nodes.json     - Stored node configurations       │
└─────────────────────────────────────────────────────────────┘
                         │
                SSH Tunnel (-L)
                         │
┌─────────────────────────────────────────────────────────────┐
│  Remote Server                                              │
│                                                             │
│  /tmp/nanobot-xxx/                                          │
│  └── nanobot-node.py   - WebSocket server + tmux wrapper   │
│                                                             │
│  tmux session "nanobot"  - Maintains command context        │
└─────────────────────────────────────────────────────────────┘
```

## Module Details

### nanobot/nodes/config.py

**Purpose**: Configuration data structures

**Classes**:
- `NodeConfig`: Single node configuration
  - `name`: Node identifier
  - `ssh_host`: SSH connection string (user@host)
  - `ssh_port`: SSH port (default: 22)
  - `ssh_key_path`: Optional SSH key path
  - `remote_port`: WebSocket port on remote (default: 8765)
  - `local_port`: Local SSH tunnel port (auto-assigned)
  - `auth_token`: Optional authentication token
  - `workspace`: Default working directory

- `NodesConfig`: Collection of nodes
  - `add_node()`: Add node configuration
  - `remove_node()`: Remove node
  - `get_node()`: Get node by name
  - `save()`: Save to file
  - `load()`: Load from file

**Storage**: `~/.nanobot/nodes.json`

### nanobot/nodes/connection.py

**Purpose**: Remote node connection management

**Classes**:
- `RemoteNode`: Single remote node connection

**Key Methods**:
- `setup()`: Establish connection
  1. Generate unique session ID
  2. Create SSH tunnel
  3. Deploy node script
  4. Start node process
  5. Connect WebSocket
  6. Authenticate

- `teardown()`: Clean up resources
  1. Close WebSocket
  2. Stop node process
  3. Clean remote temp files
  4. Close SSH tunnel

- `execute()`: Execute command remotely
  1. Send WebSocket message
  2. Wait for response
  3. Return result

**Flow**:
```
setup()
  ├─ _create_ssh_tunnel()
  │   └─ ssh -N -L local:remote user@host
  ├─ _deploy_node()
  │   ├─ mkdir /tmp/nanobot-xxx/
  │   └─ base64 encode script
  ├─ _start_node()
  │   └─ uv run nanobot-node.py
  ├─ _connect_websocket()
  │   └─ websockets.connect(ws://localhost:port)
  └─ _authenticate()
      └─ Send token, wait for ack
```

### nanobot/nodes/manager.py

**Purpose**: Manage multiple remote nodes

**Classes**:
- `NodeManager`: Multi-node manager

**Key Methods**:
- `add_node()`: Add and save node config
- `remove_node()`: Remove and disconnect node
- `connect()`: Connect to a node
- `disconnect()`: Disconnect from a node
- `execute()`: Execute command on node
- `execute_on_all()`: Execute on all connected nodes

**Connection Pooling**:
- Maintains dict of `name -> RemoteNode`
- Auto-connects on execute if not connected
- Lazy connection (only connects when needed)

### nanobot/agent/tools/nodes.py

**Purpose**: User-facing tool for node management

**Tool Actions**:
| Action | Method | Description |
|--------|--------|-------------|
| `list` | `_list_nodes()` | Show all nodes and status |
| `add` | `_add_node()` | Add new node configuration |
| `remove` | `_remove_node()` | Remove node |
| `connect` | `_connect_node()` | Connect to node |
| `disconnect` | `_disconnect_node()` | Disconnect from node |
| `status` | `_node_status()` | Show node details |
| `exec` | `_exec_command()` | Execute command on node |

**Usage**:
```
nodes action="list"
nodes action="add" name="server" ssh_host="user@host"
nodes action="exec" name="server" command="ls -la"
```

### Modified Tools

#### shell.py (ExecTool)

**Changes**:
- Added `node_manager` parameter
- Added `node` parameter to schema
- Added `_execute_remote()` method
- Delegates to NodeManager for remote execution

**Flow**:
```
execute(command, node=None)
  ├─ if node and node_manager:
  │   └─ _execute_remote(command, node)
  │       └─ node_manager.execute(command, node)
  └─ else:
      └─ _execute_local(command)
```

#### filesystem.py (ReadFileTool, WriteFileTool)

**Changes**:
- Added `node_manager` parameter
- Added `node` parameter to schema
- Added `_read_remote()`, `_write_remote()` methods
- Uses `cat` for reading, `base64` for writing

**Write Strategy**:
```
_write_remote(path, content, node)
  ├─ base64.b64encode(content)
  ├─ node_manager.execute(
  │     f"mkdir -p $(dirname {path}) && echo {encoded} | base64 -d > {path}",
  │     node
  │   )
  └─ Return result
```

### scripts/nanobot-node.py

**Purpose**: Deploy to remote servers

**Components**:
- `TmuxSession`: Manages tmux session
- `CommandExecutor`: Executes commands via tmux
- `handle_connection()`: WebSocket handler

**Protocol**:
```json
// Authentication
{"token": "optional-token"}

→ {"type": "authenticated", "message": "..."}

// Execute command
{"type": "execute", "command": "ls -la"}

→ {"type": "result", "success": true, "output": "...", "error": null}

// Ping/pong
{"type": "ping"}

→ {"type": "pong"}

// Close
{"type": "close"}
```

**Usage**:
```bash
# On remote server
uv run --with websockets nanobot-node.py --port 8765 --token secret

# Without tmux (no session persistence)
uv run --with websockets nanobot-node.py --no-tmux
```

## Integration with Existing Tools

### Tool Initialization

To enable remote node support in tools:

```python
from nanobot.nodes.manager import NodeManager
from nanobot.nodes.config import NodesConfig

# Create node manager
config = NodesConfig.load(NodesConfig.get_default_config_path())
node_manager = NodeManager(config)

# Initialize tool with node manager
exec_tool = ExecTool(node_manager=node_manager)
read_tool = ReadFileTool(node_manager=node_manager)
write_tool = WriteFileTool(node_manager=node_manager)
```

### Tool Parameter Flow

```
User Request
    ↓
LLM generates tool call
    ↓
Tool.execute(command="...", node="server")
    ↓
Tool checks node parameter
    ↓
If node set:
    node_manager.execute(command, node)
    ↓
RemoteNode.execute(command)
    ↓
WebSocket → Remote → Execute → Return
    ↓
Result to user
```

## Error Handling

### Connection Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| SSH tunnel failed | SSH not accessible | Check SSH connectivity |
| WebSocket timeout | Node not started | Check remote Python/uv |
| Authentication failed | Invalid token | Check token config |
| Connection lost | Network issue | Auto-reconnect |

### Command Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| Timeout | Long-running command | Use background mode |
| Command failed | Invalid command | Check command syntax |
| Session lost | tmux crashed | Reconnect (recreates session) |

## Testing

### Unit Tests

See `scripts/test_remote_node.py`:

```python
# Test config
test_config()
test_nodes_config()
test_remote_node_config()
```

### Integration Testing

To test with real SSH:

1. Set up test VM/container
2. Add node config
3. Test connection
4. Test command execution
5. Verify cleanup

### Manual Testing Checklist

- [ ] Add node configuration
- [ ] Connect to node
- [ ] Execute simple command (`ls`)
- [ ] Execute command with cd
- [ ] Verify session persistence
- [ ] Read remote file
- [ ] Write remote file
- [ ] Disconnect
- [ ] Verify cleanup (no /tmp files left)

## Performance

### Connection Latency

| Operation | Time | Notes |
|-----------|------|-------|
| SSH tunnel | ~200ms | First connection |
| Deploy script | ~500ms | First connection |
| Start node | ~2s | First connection (uv install) |
| WebSocket connect | ~50ms | After tunnel |
| Command execution | ~10ms | Per command |
| Subsequent connections | ~250ms | With existing node |

### Optimization

- **Connection Pooling**: Reuse connections
- **Lazy Connection**: Only connect when needed
- **Session Reuse**: tmux persists between commands
- **SSH Tunnel Keepalive**: Maintained by SSH

## Future Enhancements

### Planned

1. **Streaming Output**: Real-time command output
2. **File Transfer**: Optimized large file handling
3. **Parallel Execution**: Execute on multiple nodes
4. **Health Monitoring**: Auto-reconnect on failure
5. **Certificate Auth**: SSH certificate support

### Considered

1. **Reverse WebSocket**: Remote connects to Gateway
2. **HTTP Fallback**: Non-WebSocket option
3. **Docker Support**: Execute in containers
4. **Kubernetes Support**: Pod execution

## Security Notes

### Threat Model

| Threat | Mitigation |
|--------|------------|
| SSH hijacking | Use SSH keys, strong auth |
| WebSocket sniffing | Tunnel through SSH (encrypted) |
| Command injection | Input validation, guards |
| Token leakage | Don't log tokens, env vars |
| Temp file exposure | /tmp permissions (user-only) |

### Best Practices

1. Use SSH keys, not passwords
2. Set unique auth tokens per node
3. Limit node permissions (principle of least privilege)
4. Use workspace restrictions
5. Monitor for unusual activity

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific modules
logging.getLogger("nanobot.nodes").setLevel(logging.DEBUG)
```

### Common Issues

**Issue**: "SSH tunnel failed"
- Check: `ssh user@host` works
- Check: SSH port is correct
- Check: Firewall allows connection

**Issue**: "WebSocket connection timeout"
- Check: Remote has Python 3.11+
- Check: Remote has `uv` installed
- Check: Remote can install `websockets`

**Issue**: "Command not found on remote"
- Check: PATH on remote
- Check: Use absolute paths
- Check: Command exists on remote

## Contributing

### Adding New Node-Aware Tools

1. Add `node_manager` parameter to `__init__`
2. Add `node` to parameters schema
3. Add remote execution method
4. Update tool description

Example:
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

### Adding New Node Actions

1. Add action to `parameters["enum"]` in NodesTool
2. Add handler method (`_action_name`)
3. Update description with usage
4. Add error handling

## References

- [Design Document](./NANOBOT_NODE_ENHANCEMENT.md)
- [Usage Guide](./USAGE.md)
- [Original Fork](https://github.com/EisonMe/nanobot)
