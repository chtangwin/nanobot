# Implementation: How "run X on server" Works

## Overview

When user says "run X on server", nanobot needs to:
1. Know about the remote host (server)
2. Route the command to the correct remote
3. Execute via the remote agent
4. Return results seamlessly

## What's Needed

### 1. Host Registry

Store remote host configurations:

```python
# hosts.json or in-memory
{
  "prod-server": {
    "host": "prod.example.com",
    "user": "admin",
    "auth": "ssh_key",  # or password
    "status": "connected"  # or "disconnected"
  },
  "build-server": { ... }
}
```

**LLM awareness:** Include available hosts in system prompt:
```
You have access to remote hosts:
- prod-server (connected)
- build-server (connected)

Use "on <host>" syntax to run commands on remote.
```

### 2. Host-Aware Tools

Extend existing tools with a `host` parameter:

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
        return remote_exec(host, command)  # via WebSocket
```

Same for `read_file`, `write_file`, etc.

### 3. Natural Language Parsing

**Option A: Explicit syntax** (simpler)
```
User: "run pytest on prod-server"
→ LLM calls: exec(command="pytest", host="prod-server")
```

**Option B: Context-aware** (smarter)
```
User: "run pytest"  (if prod-server is current context)
→ LLM calls: exec(command="pytest", host="prod-server")
```

LLM learns from conversation context which host is "active".

### 4. System Prompt Enhancements

Add to system prompt:

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

### 5. Tool Routing

```python
async def exec(command: str, host: str = "local"):
    if host == "local":
        return await local_exec(command)
    
    # Get remote connection
    connection = connections.get(host)
    if not connection:
        # Auto-connect if needed
        connection = await connect_to_node(host)
    
    # Send to remote agent via WebSocket
    result = await connection.execute(command)
    return result
```

### 6. Connection Management

- **Auto-connect** on first remote command
- **Persist** WebSocket connection during session
- **Reconnect** automatically if dropped
- **Cleanup** when user explicitly disconnects

## Example Flow

```
User: "run pytest on build-server"

1. LLM sees "build-server" → knows it's a remote host
2. LLM calls: exec(command="pytest", host="build-server")
3. Tool checks: host != "local" → routes to remote
4. Remote agent executes: subprocess.run("pytest")
5. Output returned to user
```

```
User: "read main.py on prod-server"

1. LLM calls: read_file(path="main.py", host="prod-server")
2. Tool routes to remote
3. Remote agent: reads file, returns content
4. User gets file content as if local
```

## Key Design Decisions

| Decision | Option | Recommendation |
|----------|--------|----------------|
| Tool design | Separate tools (exec_remote) vs unified (exec + host param) | Unified — simpler for LLM |
| Host specification | Explicit ("on server") vs context | Both — explicit wins, context as fallback |
| Connection timing | Lazy (on first command) vs eager (on add) | Lazy — faster to add hosts |
| Multi-host commands | Sequential vs parallel | Parallel for independent commands |

## What to Implement First

1. **Host config storage** — add host definitions
2. **Basic exec with host param** — simplest remote command
3. **System prompt update** — make LLM aware
4. **Connection pool** — manage remote connections
5. **Add more host-aware tools** — read_file, write_file, etc.
