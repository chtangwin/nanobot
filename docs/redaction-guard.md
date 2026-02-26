# Redaction Guard - Sensitive Data Protection

## Overview

Redaction Guard is a security feature that protects sensitive information from being exposed through the nanobot agent. It provides three layers of protection to prevent accidental leakage of API keys, passwords, credentials, and other sensitive data.

## Features

### Layer 1: Block Sensitive File Access

Prevents the agent from reading or writing to sensitive files that may contain credentials:

- Environment files: `.env`, `.env.local`, `.env.production`
- Authentication files: `auth.json`, `oauth.json`
- SSH keys: `id_rsa`, `id_rsa.pub`, `id_ed25519`, `id_ed25519.pub`
  - **Pattern**: `^id_[a-z0-9-]+(\.pub)?$` - supports all current and future SSH key algorithms
- Certificate files: `.pem`, `.p12`, `.pfx`, `.jks`, `.key`
  - **Backup files also blocked**: `.pem.bak`, `.key.old`, `.p12.tmp`, etc.
- Secrets files: `secrets.json`, `secrets.yaml`, `credentials.json`, etc.

When attempting to access these files, the agent receives an error message:
```
Error: Access to sensitive path is blocked by redaction policy: /path/to/.env
```

### Layer 2: Redact Tool Outputs

Automatically redacts sensitive information from tool execution results before they are added to the conversation history. This prevents sensitive data from being stored or sent to the LLM.

### Layer 3: Redact Context

Redacts sensitive information from all messages right before they are sent to the LLM, including:
- System prompts
- User messages
- Assistant messages
- Tool results

## Configuration

Add or update the `tools` section in `~/.nanobot/config.json`:

```json
{
  "tools": {
    "blockSensitiveFiles": true,
    "redactToolOutputs": true,
    "redactContext": true
  }
}
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `blockSensitiveFiles` | boolean | `true` | Block access to sensitive files |
| `redactToolOutputs` | boolean | `true` | Redact sensitive data from tool outputs |
| `redactContext` | boolean | `true` | Redact sensitive data before sending to LLM |

All options are enabled by default for maximum security.

## Redaction Rules

The following patterns are automatically redacted. All patterns use minimum length requirements to reduce false positives:

| Pattern | Example | Redacted | Min Length |
|---------|---------|----------|------------|
| Private Key Block | `-----BEGIN PRIVATE KEY-----...` | `[REDACTED_PRIVATE_KEY]` | 10KB limit |
| OpenAI API Key | `sk-abc123...` (32+ chars) | `sk-***` | 32 chars |
| GitHub PAT | `ghp_xxxxxxxx...` (20+ chars) | `gh***` | 20 chars |
| Slack Token | `xoxb-...` (10+ chars) | `xox***` | 10 chars |
| Bearer Token | `Bearer eyJhbGci...` (20+ chars) | `Bearer ***` | 20 chars |
| API Key KV | `api_key=abc123...` (8+ chars) | `api_key=***` | 8 chars |
| Password KV | `password=mypassword` | `password=***` | N/A |
| Token KV | `access_token=abc123` | `access_token=***` | N/A |
| Secret KV | `client_secret=abc123` | `client_secret=***` | N/A |

**Notes**:
- Minimum length requirements reduce false positives (e.g., `sk-test` won't be redacted)
- Patterns support keys in any position (start, middle, or end of string)
- Private key pattern has a 10KB limit to prevent DoS attacks

## Security Considerations

- **Idempotent**: Running redaction multiple times produces the same result. Already-redacted text will not be modified again.
- **Layered Protection**: Even if one layer is disabled, other layers still provide protection.
- **Fail-Safe Defaults**: All redaction features are enabled by default.

## Testing

Run the redaction tests:

```bash
pytest tests/test_redaction.py -v
```

All 33 tests are organized into 4 test classes:

- **TestSensitivePath** (12 tests): File type detection, path traversal attacks, backup files, case-insensitive matching
- **TestRedactText** (15 tests): All redaction patterns, idempotency, keys in middle of strings
- **TestRedactContent** (3 tests): String, list, and mixed content redaction
- **TestRedactMessages** (3 tests): Message history and structure preservation

## Related Files

- `nanobot/agent/tools/redaction.py` - Core redaction logic and patterns
- `nanobot/agent/tools/filesystem.py` - Layer 1 (file access blocking)
- `nanobot/agent/tools/shell.py` - ExecTool (bash command execution)
- `nanobot/agent/context.py` - Layer 2 & 3 (tool outputs and context redaction)
- `nanobot/config/schema.py` - Configuration schema (ToolsConfig)
- `tests/test_redaction.py` - Test suite (33 tests)

## Code Simplification Opportunities

The current implementation provides three separate configuration flags for flexibility. To make the code more minimal:

1. **Remove redundant flags**: Consolidate `redactToolOutputs` and `redactContext` into a single `redact` flag
2. **Enable by default**: Redaction should always be active for security, so flags could be removed entirely
3. **Reduce comments**: Some inline comments could be simplified or removed

**Current config**:
```json
{
  "tools": {
    "blockSensitiveFiles": true,
    "redactToolOutputs": true,
    "redactContext": true
  }
}
```

**Simplified config** (future):
```json
{
  "tools": {
    "blockSensitiveFiles": true
  }
}
```

With redaction always enabled by default.
