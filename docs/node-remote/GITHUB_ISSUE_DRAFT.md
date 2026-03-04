# feat: Remote Host Feature Proposal

## The Goal

We would like to achieve the following:
- Just say "run X on server" — it runs on remote
- Use nanobot tools, skills, LLM together with remote data/outputs — same experience as using local
- Minimalist code, zero installation on remote machine

## The Problem

Right now, nanobot can do a ton of cool stuff locally:

- Run subagents to analyze code
- Use tools like read_file, exec, write_file
- Chain multiple tools together

But if I want to work with remote servers? It's manual:

```
Me: "SSH into prod-server, check the code"
Me: *SSH in*
Me: *Copy files back locally*
Me: *Now I can finally use nanobot tools*
```

This basically breaks the whole agent workflow for remote machines. 
I can't just say "run kubectl get pods and tell me which services have issues" and have nanobot do its thing.

## Remote Requirements

The remote server needs only these basic tools:

- **bash** — for shell commands
- **uv** — to run the Python agent (auto-installed via curl if missing)
- **tmux** — for session persistence (used internally by nanobot)

That's it. No nanobot-specific packages, no Docker, nothing else.

## Key Features & Examples

### Feature 1: Seamless Remote Command Execution

Run commands on remote machines as easily as local ones — just specify the server.

```
User: "run pytest on build-server"
→ SSH to build-server, run pytest, return results

User: "check disk usage on prod-server"
→ Returns: "/dev/sda1: 80% used, /dev/sda2: 45% used"
```

**Use case:** Quick ad-hoc commands across multiple servers without managing SSH sessions manually.

---

### Feature 2: Remote Files as Local Files

Access remote files using the same nanobot tools you use locally — no mental context switching.

```
User: "read main.py on prod-server"
→ reads remote file, returns content (same as reading local file)

User: "grep -r 'TODO' on prod-server:/app/"
→ searches in remote directory, returns matches
```

**Use case:** Inspecting configuration files, reading logs, searching code on servers without SSHing in.

---

### Feature 3: Persistent Sessions & Session Memory

This is the killer feature. Start background processes, disconnect, come back later — everything preserved.

```
# Session 1
User: "start dev server on build-server: cd /app && npm run dev"
→ starts dev server in background, PID 12345, port 3000

# 2 hours later - Session 2
User: "check the dev server"
→ "Server running for 2 hours, port 3000, memory: 256MB"

User: "tail the logs"
→ "Last 20 lines: [INFO] Server started at 10:30..."

User: "restart it with fresh logs"
→ kills old process, restarts, new PID 12346
```

What's preserved:
- **Working directory** — `cd /app` survives reconnect
- **Environment variables** — `NODE_ENV=production` persists
- **Shell state** — aliases, functions, variables all persist
- **Running processes** — background jobs keep running

**Use case:** Running dev servers, long-running data jobs, background tasks that need monitoring.

---

### Feature 4: AI-Powered Remote Analysis with is what makes remote hosts genuinely useful — Subagents

This not just a fancy SSH wrapper.

```
User: "check the logs on prod-server, any issues?"
→ subagent patterns, explains problems:
  "Found 3 errors:
   1. reads logs, analyzes Database connection timeout (10 occurrences)
   2. Failed auth attempts from IP 192.168.1.100
   3. Memory leak in worker process"
```

The real magic: **LLM + tools + remote = AI that works where the data lives**

```
User: "Analyze payment service on prod-server, find security issues"

Subagent on remote:
  1. read_file → reads all payment/*.py files
  2. grep → searches for hardcoded secrets, passwords, tokens
  3. exec → runs static analysis tools
  4. LLM → semantically analyzes code for vulnerabilities
  5. Returns: "Found 4 issues..."

You get AI analysis without:
- Copying files locally
- Installing tools on prod
- Manually interpreting results
```

**Use case:** Security audits, debugging, code analysis — AI works directly on remote data.

---

## Host Types: Local vs Remote

nanobot already works great locally. Here we adopt the "host" concept, which can be either local (default) or remote.

```
  Hosts:                                   
  ├── default (local)  ← current          
  └── remote           ← new!             
      ├── build-server                     
      ├── prod-server                      
      └── ...                              
```

Now we extend all capabilities to remote machines by using hosts in conversation:

- `"read main.py"` — reads local file
- `"read main.py on prod-server"` — reads remote file

---

## How It Works

### First Connection: SSH + Deploy

When you first connect to a remote server, nanobot sets up a lightweight agent on that machine:

1. **SSH Connect** — nanobot establishes an SSH connection to the remote server
2. **Create Working Directory** — A temporary directory is created on the remote (`/tmp/nanobot-xxx/`)
3. **Deploy Agent Script** — The Python agent script is base64-encoded, sent over SSH, and written to the remote directory
4. **Start WebSocket Server** — The agent runs via `uv run remote_server.py`, which starts a WebSocket server listening on `localhost` only
5. **SSH Tunnel Setup** — nanobot creates an SSH tunnel (`-L 8765:localhost:8765`) to connect to the remote WebSocket server

After this one-time setup, all communication flows through the SSH tunnel. No ports need to be opened on the remote — the connection is outbound from your machine, so it works through firewalls and NAT without any manual tweaks.

### Ongoing Communication: WebSocket

Once connected, all communication happens over a WebSocket tunnel through the SSH connection:

- **Command Execution** — Send shell commands, receive output
- **File Operations** — Read, write, list files on remote
- **Subagent Spawning** — Run AI agents directly on the remote with full tool access
- **Session Management** — Track working directory, environment, running processes

The WebSocket connection persists until you explicitly disconnect, enabling true interactive sessions.

**Connection Resilience:** If the SSH or WebSocket connection drops (network hiccup, laptop sleep, WiFi switch), nanobot automatically reconnects. Your session state — working directory, environment variables, running processes — all persist on the remote. You pick up right where you left off. The only way to end a session is explicitly calling cleanup.

### Cleanup: When Done

When you're finished working with a remote host:

1. **Disconnect Command** — You tell nanobot to disconnect from the server
2. **Signal Cleanup** — nanobot sends a cleanup signal to the remote agent
3. **Remove Traces** — The remote agent deletes `/tmp/nanobot-xxx/` and all its contents
4. **Close Connection** — WebSocket is closed, SSH session ends

The server looks untouched — no installed packages, no lingering files, no traces left behind.

---

## Comparison: SSH vs SSH+tmux skill vs Remote Hosts

| | Plain SSH | SSH + tmux skill (nanobot) | Remote Hosts |
|---|---|---|---|
| **What you say** | `ssh user@server` + manual commands | Natural language, skill manages tmux | "run X on server" (natural language) |
| **Session after disconnect** | ❌ Dies | ✅ Survives (skill auto-reattaches) | ✅ Survives + auto-reconnect |
| **Auto-reconnect** | ❌ | ✅ | 🟢 Seamless |
| **AI analysis** | ❌ Manual | ❌ Manual | 🟢 Subagent runs directly on remote |
| **tmux management** | None | Skill handles it | nanobot manages it for you |

---

## Why This Is Cool

| Feature | Why It Matters |
|---------|----------------|
| 🚀 **Minimal setup** | Just SSH + basic tools (bash, uv, tmux) |
| 👻 **Zero trace** | /tmp/ cleanup, like it never happened |
| 🔄 **Persistent sessions** | Start background jobs, dev servers, come back hours later |
| 🔄 **Session memory** | Directory, environment, all preserved |
| 🔒 **Secure** | Token auth + optional SSH |
| 🌐 **Works through NAT** | SSH tunnel (no port opening) |
| 🤖 **Subagent support** | Actually useful for real work |
| 🧠 **LLM + Tools on remote** | AI analyzes code in place, no data transfer |

---

> Related discussion: https://github.com/HKUDS/nanobot/issues/775 (some implementation ideas may be borrowed from this issue)

Feedback are welcome. If there's enough interest, I'll implement it!
