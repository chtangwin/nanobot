# Local Host Resolution

## Overview

This enhancement allows nanobot to automatically detect when a host defined in `hosts.json` refers to the local machine, and route operations to the `LocalExecutionBackend` instead of creating unnecessary SSH tunnels and WebSocket connections.

## Problem

Previously, even if a host in `hosts.json` pointed to `localhost` or a local IP address, nanobot would:
1. Create an SSH tunnel to localhost
2. Deploy `remote_server.py`
3. Establish a WebSocket connection
4. Execute commands through the remote server

This added unnecessary overhead for local hosts.

## Solution

Added local host detection in `ExecutionBackendRouter.resolve()`:

```python
async def resolve(self, host: str | None = None) -> ExecutionBackend:
    if not host:
        return self.local_backend
    if not self.host_manager:
        raise RuntimeError("Host manager not available")

    # Check if the host refers to the local machine
    host_config = self.host_manager.config.get_host(host)
    if host_config and is_localhost(host_config.ssh_host):
        # Host is actually local - use local backend
        return self.local_backend

    # Host is remote - use remote backend
    remote_host = await self.host_manager.get_or_connect(host)
    return RemoteExecutionBackend(host, remote_host)
```

## Changes Made

### 1. New Module: `nanobot/agent/backends/localhost.py`

Lightweight utility module with a single function:

- `is_localhost(ssh_host: str | None) -> bool`: Checks if a host string refers to the local machine

**Detection Criteria**:
- `localhost`, `127.0.0.1`, `::1`, `0.0.0.0`
- Any `127.x.x.x` IP address
- Actual local IPs assigned to network interfaces
- Local machine's hostname

### 2. Modified: `nanobot/agent/backends/router.py`

Updated `ExecutionBackendRouter.resolve()` to check if the host is local before creating a `RemoteExecutionBackend`.

### 3. Modified: `nanobot/agent/tools/hosts.py`

`HostsTool._exec_command()` now delegates to `ExecTool.execute(command, host=name)` instead of calling `host_manager.get_or_connect()` directly. This ensures the `hosts action="exec"` path goes through the same `ExecutionBackendRouter` as all other tools, including localhost detection.

### 4. Modified: `nanobot/agent/loop.py`

Pass `exec_tool` reference to `HostsTool` during tool registration.

## Detection Examples

All of these would be detected as local:

```json
{
  "hosts": {
    "local-alias": {
      "ssh_host": "localhost"
    },
    "local-127": {
      "ssh_host": "root@127.0.0.1"
    },
    "local-ip": {
      "ssh_host": "user@10.0.0.72"
    },
    "local-hostname": {
      "ssh_host": "user@SP6"
    }
  }
}
```

## Benefits

1. **Zero overhead**: Local hosts bypass SSH/WebSocket setup
2. **Faster execution**: No network latency
3. **Clean implementation**: Single point of decision in router
4. **Transparent**: Works automatically without configuration changes
5. **Backward compatible**: Existing `hosts.json` files work without modification

## Usage

No changes needed to existing workflows. If you have a host entry that points to localhost or a local IP, it will automatically be routed to the local backend.

**Both tool paths work identically**:

```
# Via ExecTool — router detects localhost, runs locally
exec(host="my-local", command="ls -la")

# Via HostsTool — delegates to ExecTool, same path
hosts(action="exec", name="my-local", command="ls -la")
```

## Technical Details

### Detection Algorithm

```python
def is_localhost(ssh_host: str | None) -> bool:
    1. Parse "user@host" format to extract hostname
    2. Check against localhost aliases (localhost, 127.0.0.1, ::1, 0.0.0.0)
    3. Check if in loopback range (127.x.x.x)
    4. Get all local IPs via socket connection to 8.8.8.8
    5. Check if hostname matches local IPs
    6. Try DNS resolution and check if result is local
    7. Check against local hostname/FQDN
```

### Execution Flow

Both `exec(host=...)` and `hosts(action="exec", name=...)` reach the same path:

```
exec(host="myserver", command="ls")          hosts(action="exec", name="myserver", command="ls")
    ↓                                             ↓
ExecTool.execute(command, host)              HostsTool._exec_command(name, command)
    ↓                                             ↓  delegates to ExecTool
    └──────────────────┬───────────────────────────┘
                       ↓
         ExecutionBackendRouter.resolve("myserver")
                       ↓
         is_localhost(host_config.ssh_host)?
           ├─ Yes → LocalExecutionBackend (direct)
           └─ No  → RemoteExecutionBackend (SSH → WS → remote_server)
```

## Testing

Run manual verification:

```python
# Create a test hosts.json
{
  "hosts": {
    "test-local": {
      "ssh_host": "localhost"
    }
  }
}

# Use it in nanobot
hosts action="exec" name="test-local" command="echo test"

# Should execute locally without SSH/WebSocket
```

## Comparison with Previous Approach

### Before (Messy Implementation)
- Modified `RemoteHost` class extensively
- Added local execution paths throughout `connection.py`
- Complex logic in multiple methods
- Hard to maintain and debug

### After (Clean Implementation)
- Single decision point in `router.py`
- Small utility module (`localhost.py`)
- No changes to `RemoteHost` or other components
- Easy to understand and maintain

## Future Enhancements

Possible improvements:
- Configurable detection rules
- IPv6 support
- Explicit `is_local` flag in `HostConfig`
- Detection logging for debugging
