# Remote Node Quick Start

Get started with nanobot remote nodes in 5 minutes.

## Prerequisites

### Local (Your Machine)
- ✅ nanobot installed
- ✅ SSH client
- ✅ Python 3.11+

### Remote (Server)
- ✅ SSH access
- ✅ Python 3.11+ OR `uv` (will auto-install if missing)
- ✅ `tmux` (recommended, for session persistence)

## 5-Minute Setup

### Step 1: Add Your First Node

```
You: Add a node called "myserver" at user@192.168.1.100

Nanobot uses:
nodes action="add" name="myserver" ssh_host="user@192.168.1.100"

Response: ✓ Node 'myserver' added successfully
```

### Step 2: Connect

```
You: Connect to myserver

Nanobot uses:
nodes action="connect" name="myserver"

Response: ✓ Connected to 'myserver' (session: nanobot-a1b2c3d4)
```

### Step 3: Execute Commands

```
You: Run ls -la on myserver

Nanobot uses:
exec command="ls -la" node="myserver"

Response: [directory listing]
```

## Common Commands

### List All Nodes
```
nodes action="list"
```

### Check Node Status
```
nodes action="status" name="myserver"
```

### Execute Multiple Commands
```
You: Check the disk space on myserver
exec command="df -h" node="myserver"

You: What's in /var/log?
exec command="ls /var/log" node="myserver"

You: Show me the last 20 lines of syslog
exec command="tail -20 /var/log/syslog" node="myserver"
```

### Read Remote Files
```
read_file path="/etc/nginx/nginx.conf" node="myserver"
```

### Write Remote Files
```
write_file path="/tmp/test.txt" node="myserver" content="Hello from nanobot!"
```

## Session Persistence Example

```
You: cd to /app on myserver
exec command="cd /app" node="myserver"

You: list files
exec command="ls" node="myserver"
→ [shows files in /app, session persists!]

You: Check git status
exec command="git status" node="myserver"
→ [still in /app directory]
```

## Disconnect When Done

```
nodes action="disconnect" name="myserver"

Response: ✓ Disconnected from 'myserver'

[Remote cleanup happens automatically]
```

## Troubleshooting

### Connection Fails

```bash
# Test SSH manually first
ssh user@192.168.1.100

# Check if remote has Python
ssh user@192.168.1.100 "python3 --version"

# Check if remote has uv
ssh user@192.168.1.100 "uv --version"

# If uv missing, install on remote:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Permission Denied

```bash
# Make sure your SSH key works
ssh -i ~/.ssh/id_rsa user@192.168.1.100

# Or specify key when adding node
nodes action="add" name="myserver" ssh_host="user@host" ssh_key_path="~/.ssh/id_rsa"
```

### Can't Find Command

```bash
# Use absolute paths
exec command="/usr/bin/python3 script.py" node="myserver"

# Or check PATH first
exec command="echo \$PATH" node="myserver"
```

## Real-World Examples

### Deploy to Production

```
You: Deploy the new version to prod-server

Nanobot will:
1. exec command="cd /app && git pull" node="prod-server"
2. exec command="cd /app && npm install" node="prod-server"
3. exec command="pm2 restart myapp" node="prod-server"
4. exec command="pm2 status" node="prod-server"

Done in 30 seconds!
```

### Run Tests on Build Server

```
You: Run the full test suite on build-server

Nanobot will:
1. Connect to build-server
2. exec command="cd /app && pytest -v" node="build-server"
3. Show test results

No need to SSH manually!
```

### Analyze Remote Code

```
You: Analyze the code structure on myserver

Nanobot can use subagent with node context:
1. read_file path="/app/main.py" node="myserver"
2. read_file path="/app/utils.py" node="myserver"
3. analyze code structure
4. Provide summary
```

## Tips

1. **Use Descriptive Names**: `prod-server`, `build-node`, `staging-db`
2. **Set Workspace**: Configure default directory per node
3. **Session Persistence**: tmux keeps your working directory
4. **Auto-Cleanup**: Everything is removed on disconnect
5. **Multiple Nodes**: Manage several servers simultaneously

## Next Steps

- Read [USAGE.md](./USAGE.md) for detailed examples
- Read [IMPLEMENTATION.md](./IMPLEMENTATION.md) for technical details
- Check [NANOBOT_NODE_ENHANCEMENT.md](./NANOBOT_NODE_ENHANCEMENT.md) for design rationale

## Need Help?

Common issues and solutions in [USAGE.md#troubleshooting](./USAGE.md#troubleshooting)
