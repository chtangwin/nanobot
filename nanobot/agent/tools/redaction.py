"""Redaction guard - protects sensitive information from being exposed."""

import re
from typing import Any

# Sensitive file path patterns (used to block file access)
SENSITIVE_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|[\\/])\.env(\..+)?$", re.I),
    re.compile(r"(^|[\\/])auth\.json$", re.I),
    re.compile(r"(^|[\\/])oauth\.json$", re.I),
    re.compile(r"(^|[\\/])id_rsa(\.pub)?$", re.I),
    re.compile(r"(^|[\\/])id_ed25519(\.pub)?$", re.I),
    re.compile(r"\.pem$", re.I),
    re.compile(r"\.p12$", re.I),
    re.compile(r"\.pfx$", re.I),
    re.compile(r"\.jks$", re.I),
    re.compile(r"\.key$", re.I),
    re.compile(r"(^|[\\/])\.secrets$", re.I),
    re.compile(r"(^|[\\/])secrets?\.", re.I),
    re.compile(r"(^|[\\/])credentials?\.", re.I),
]

# Redaction rules for sensitive data
# Order matters: more specific patterns should come first
REDACTION_RULES: list[tuple[str, re.Pattern[str], str]] = [
    # Private keys (most specific - must match full key)
    (
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # OpenAI API keys (specific format)
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "sk-***"),
    # GitHub PATs
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "gh***"),
    # Slack tokens
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "xox***"),
    # Bearer tokens
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+\/-]+=*\b", re.I), "Bearer ***"),
    # Password key-value patterns (must be before general api_key to avoid partial matches)
    (
        "password_kv",
        re.compile(r"(\bpassword\b\s*[:=]\s*[\"']?)[^\"'\s,}]+([\"']?)", re.I),
        r"\1***\2",
    ),
    # API key key-value patterns
    (
        "api_key_kv",
        re.compile(r"(\bapi[_-]?key\b\s*[:=]\s*[\"']?)[^\"'\s,}]+([\"']?)", re.I),
        r"\1***\2",
    ),
    # Token key-value patterns
    (
        "token_kv",
        re.compile(r"(\b(token|access[_-]?token|refresh[_-]?token)\b\s*[:=]\s*[\"']?)[^\"'\s,}]+([\"']?)", re.I),
        r"\1***\3",
    ),
    # Secret key-value patterns
    (
        "secret_kv",
        re.compile(r"(\b(secret|client[_-]?secret|private[_-]?key)\b\s*[:=]\s*[\"']?)[^\"'\s,}]+([\"']?)", re.I),
        r"\1***\3",
    ),
]


def normalize_path(path: str) -> str:
    """Normalize path separators."""
    return path.replace("\\", "/")


def is_sensitive_path(path: str) -> bool:
    """
    Check if a file path is sensitive and should be blocked.
    
    Args:
        path: The file path to check
        
    Returns:
        True if the path matches any sensitive pattern
    """
    if not path or not isinstance(path, str):
        return False
    normalized = normalize_path(path.strip())
    return any(pattern.search(normalized) for pattern in SENSITIVE_PATH_PATTERNS)


def redact_text(text: str) -> str:
    """
    Redact sensitive information from text.
    
    This function is idempotent - running it multiple times produces the same result.
    
    Args:
        text: The text to redact
        
    Returns:
        The redacted text
    """
    if not text or not isinstance(text, str):
        return text
    
    result = text
    for _name, pattern, replacement in REDACTION_RULES:
        result = pattern.sub(replacement, result)
    return result


def redact_content(content: Any) -> Any:
    """
    Redact sensitive information from arbitrary content.
    
    Supports strings, lists (e.g., message content blocks), and other types.
    
    Args:
        content: The content to redact
        
    Returns:
        The redacted content (same type as input)
    """
    if isinstance(content, str):
        return redact_text(content)
    
    if isinstance(content, list):
        # Handle list of content blocks (e.g., [{"type": "text", "text": "..."}])
        redacted = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                redacted.append({**item, "text": redact_text(item["text"])})
            else:
                redacted.append(item)
        return redacted
    
    # For other types, return as-is
    return content


def redact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Redact sensitive information from a list of messages.
    
    Args:
        messages: List of message dicts with 'content' field
        
    Returns:
        Messages with sensitive data redacted
    """
    redacted = []
    for msg in messages:
        content = msg.get("content")
        if content:
            redacted_content = redact_content(content)
            redacted.append({**msg, "content": redacted_content})
        else:
            redacted.append(msg)
    return redacted
