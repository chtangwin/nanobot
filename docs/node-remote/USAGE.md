# Remote Node Usage Guide

> How to use nanobot's remote execution capabilities

## Overview

Remote nodes allow nanobot to execute commands on remote machines as if they were local. The system:

- ✅ Requires zero installation on remote servers
- ✅ Maintains session context (tmux)
- ✅ Automatically manages SSH tunnels
- ✅ Cleans up after disconnect (zero trace)

## Quick Start

### 1. Add a Remote Node

```
User: "Add a node for build-server at user@192.168.1.100"

Nanobot will use:
nodes action="add" name="build-server" ssh_host="user@192.168.1.100"
```

### 2. Connect to the Node

```
User: "Connect to build-server"

Nanobot will use:
nodes action="connect" name="build-server"
```

### 3. Execute Commands Remotely

```
User: "Run ls -la on build-server"

Nanobot will use:
exec command="ls -la" node="build-server"
```

## Available Actions

### nodes tool actions:

| Action | Description | Required Parameters |
|--------|-------------|---------------------|
| `list` | List all configured nodes | - |
| `add` | Add a new node | `name`, `ssh_host` |
| `remove` | Remove a node | `name` |
| `connect` | Connect to a node | `name` |
| `disconnect` | Disconnect from a node | `name` |
| `status` | Get node status | `name` |
| `exec` | Execute command on node | `name`, `command` |

## Node-Aware Tools

These tools support the `node` parameter:

### exec

```
# Local execution
exec command="ls -la"

# Remote execution
exec command="ls -la" node="build-server"

# With working directory
exec command="pytest" node="build-server" working_dir="/app"
```

### read_file

```
# Local file
read_file path="/etc/config.py"

# Remote file
read_file path="/etc/nginx.conf" node="prod-server"
```

### write_file

```
# Local file
write_file path="/tmp/test.txt" content="Hello"

# Remote file
write_file path="/app/config.json" node="build-server" content='{"key": "value"}'
```

## Examples

### Example 1: Analyze Remote Project

```
User: "Connect to build-server and analyze the /app project"

Nanobot:
1. nodes action="connect" name="build-server"
2. exec command="find /app -name '*.py' | head -20" node="build-server"
3. read_file path="/app/main.py" node="build-server"
4. read_file path="/app/utils.py" node="build-server"
5. [Analysis and summary]
```

### Example 2: Run Tests on Remote Server

```
User: "Run the test suite on build-server"

Nanobot:
exec command="cd /app && pytest -v" node="build-server"
```

### Example 3: Deploy to Production

```
User: "Deploy the new version to prod-server"

Nanobot:
1. exec command="cd /app && git pull origin main" node="prod-server"
2. exec command="cd /app && pip install -r requirements.txt" node="prod-server"
3. exec command="systemctl restart myapp" node="prod-server"
4. exec command="systemctl status myapp" node="prod-server"
```

### Example 4: Session Persistence

```
User: "cd to /project on build-server"
→ exec command="cd /project" node="build-server"

User: "List files" (10 minutes later)
→ exec command="ls" node="build-server"
→ [Shows files in /project - session persists!]
```

## Configuration

### Node Configuration File

Nodes are stored in `~/.nanobot/nodes.json`:

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

### Adding Nodes with Options

```
# Basic
nodes action="add" name="server" ssh_host="user@host"

# With SSH key
nodes action="add" name="server" ssh_host="user@host" ssh_key_path="~/.ssh/id_rsa"

# With custom port
nodes action="add" name="server" ssh_host="user@host" ssh_port=2222

# With workspace
nodes action="add" name="server" ssh_host="user@host" workspace="/app"
```

## How It Works

### Connection Flow

```
1. User: "Connect to build-server"
2. Gateway: SSH → build-server
3. Gateway: Deploy nanobot-node.py to /tmp/nanobot-xxx/
4. Gateway: Start uv run nanobot-node.py (WebSocket server)
5. Gateway: Create SSH tunnel (localhost:XXXX → remote:8765)
6. Gateway: Connect WebSocket through tunnel
7. Gateway: Create tmux session on remote
8. [Ready for commands]
```

### Command Execution Flow

```
1. User: "Run pytest on build-server"
2. Gateway: WebSocket message → remote node
3. Remote: tmux send-keys "pytest"
4. Remote: tmux capture-pane
5. Remote: WebSocket response → Gateway
6. Gateway: Display result to user
```

### Cleanup on Disconnect

```
1. Gateway: Close WebSocket
2. Gateway: Kill tmux session on remote
3. Gateway: rm -rf /tmp/nanobot-xxx/
4. Gateway: Close SSH tunnel
5. [Remote server clean - no trace]
```

## Requirements

### Local (Gateway)

- Python 3.11+
- SSH client
- `websockets` package (already in nanobot dependencies)

### Remote

- SSH server
- Python 3.11+ (or uv will install it)
- `bash`
- `tmux` (optional, for session persistence)

### First Remote Connection

On first connection, remote must have:
- `uv` (curl installer will auto-install if missing)

Example:
```bash
# On remote, if uv is missing:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Troubleshooting

### Connection Fails

```
User: "Connect to build-server"
Response: "Error: Failed to connect to 'build-server': ..."

Check:
1. SSH access: ssh user@host
2. Python on remote: python3 --version
3. uv on remote: uv --version
4. Network connectivity
```

### Command Timeout

```
User: "Run long-running task on build-server"
Response: "Error: Command timed out after 30.0 seconds"

Solution:
- Use background mode: exec command="nohup command &" node="server"
- Or increase timeout in tool configuration
```

### Session Lost

```
User: "My cd didn't persist!"
→ tmux might have crashed

Solution:
- Reconnect: nodes action="connect" name="server"
- Session will be recreated
```

## Advanced Usage

### Multiple Nodes

```
User: "Run tests on all servers"

Nanobot:
1. nodes action="connect" name="build-server"
2. nodes action="connect" name="test-server"
3. exec command="pytest" node="build-server"
4. exec command="pytest" node="test-server"
```

### Subagent with Remote

```
User: "Analyze the code on build-server"

Nanobot:
1. Spawns subagent with node="build-server" context
2. Subagent uses:
   - exec(command, node="build-server")
   - read_file(path, node="build-server")
   - write_file(path, content, node="build-server")
3. Subagent returns analysis
```

### Background Tasks

```
User: "Start dev server on build-server in background"

exec command="cd /app && nohup npm run dev > /tmp/dev.log 2>&1 &" node="build-server"

# Check logs later
exec command="tail -f /tmp/dev.log" node="build-server"
```

## Security Considerations

1. **SSH Keys**: Use SSH keys instead of passwords
2. **Auth Tokens**: Set unique tokens for each node
3. **File Permissions**: Remote scripts use /tmp (per-user)
4. **Command Guards**: Local exec tool still guards dangerous commands

## Best Practices

1. **Workspace**: Set a default workspace per node
2. **Named Nodes**: Use descriptive node names (prod-1, staging, etc.)
3. **Session Management**: Disconnect when done to free resources
4. **Testing**: Test connectivity before running critical commands
5. **Backup**: Keep local backups of critical remote files

## See Also

- [Design Document](./NANOBOT_NODE_ENHANCEMENT.md)
- [Implementation Notes](./IMPLEMENTATION.md)
