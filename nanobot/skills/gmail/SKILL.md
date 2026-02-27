---
name: gmail
description: Search, read, send, draft, and delete emails via Gmail API.
homepage: https://developers.google.com/gmail/api
metadata: {"nanobot":{"emoji":"📧","requires":{"pypi":["google-api-python-client","google-auth-oauthlib"]}}}
---

# Gmail

Interact with Gmail via the Gmail API. Requires OAuth2 credentials setup.

## Setup

### 1. Install Dependencies

```bash
pip install google-api-python-client google-auth-oauthlib
```

Or with uv:
```bash
uv pip install google-api-python-client google-auth-oauthlib
```

### 2. Create OAuth2 Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Gmail API:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Gmail API" and enable it
4. Create OAuth2 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Application type: "Desktop app" or "Web application"
   - Name it "nanobot-gmail"
   - Download the credentials JSON file
5. Save credentials to `~/.nanobot/gmail/credentials.json`

### 3. First Run - Authorize

On first run, you'll be prompted to authorize via OAuth2:
```bash
python -c "from nanobot.skills.gmail.gmail import GmailClient; GmailClient().authorize()"
```

This will:
- Open a browser for Google OAuth2 login
- Save the token to `~/.nanobot/gmail/token.json`
- Allow future use without re-authorization

## Usage Examples

### Search Emails

```python
from nanobot.skills.gmail.gmail import GmailClient

gmail = GmailClient()

# Search unread emails
results = gmail.search("is:unread")

# Search from specific sender
results = gmail.search("from:boss@company.com")

# Search with date range
results = gmail.search("after:2025-01-01 before:2025-02-01")

# Search attachments
results = gmail.search("has:attachment")
```

### Read Email

```python
# Get email by ID
email = gmail.get_email("MESSAGE_ID")

# Read with full body
email = gmail.get_email("MESSAGE_ID", format="full")
```

### Send Email

```python
# Simple text email
gmail.send_email(
    to="recipient@example.com",
    subject="Hello from nanobot",
    body="This is a test email."
)

# HTML email
gmail.send_email(
    to="recipient@example.com",
    subject="HTML Email",
    body="<h1>Hello</h1><p>This is <b>HTML</b> content.</p>",
    html=True
)

# With CC and BCC
gmail.send_email(
    to="recipient@example.com",
    cc="cc@example.com",
    bcc="bcc@example.com",
    subject="Meeting Reminder",
    body="Don't forget our meeting tomorrow."
)
```

### Create Draft

```python
# Create a draft email
draft_id = gmail.create_draft(
    to="recipient@example.com",
    subject="Draft: Proposal",
    body="Here's the proposal draft..."
)
```

### Delete Email

```python
# Delete email by message ID
gmail.delete_email("MESSAGE_ID")

# Trash email (moves to trash, can be recovered)
gmail.trash_email("MESSAGE_ID")
```

## Gmail Search Operators

Common search operators:

| Operator | Description | Example |
|----------|-------------|---------|
| `from:` | Sender | `from:john@gmail.com` |
| `to:` | Recipient | `to:me@example.com` |
| `subject:` | Subject line | `subject:meeting` |
| `is:unread` | Unread emails | `is:unread` |
| `is:read` | Read emails | `is:read` |
| `is:starred` | Starred emails | `is:starred` |
| `has:attachment` | Has attachments | `has:attachment` |
| `filename:` | Attachment name | `filename:pdf` |
| `after:` / `before:` | Date range | `after:2025-01-01` |
| `label:` | Label filter | `label:important` |
| `in:` | Folder/label | `in:inbox`, `in:sent` |

Combine operators:
```python
# Unread from boss with attachment
gmail.search("is:unread from:boss@company.com has:attachment")

# Emails about project in last week
gmail.search("project after:2025-01-01")
```

## Return Format

### Search Results

```python
{
    "messages": [
        {
            "id": "123456789abcdef",
            "threadId": "123456789abcdef",
            "snippet": "Preview text of the email...",
            "date": "2025-02-10T14:30:00Z",
            "from": "sender@example.com",
            "to": ["recipient@example.com"],
            "subject": "Email Subject",
            "labels": ["INBOX", "UNREAD"]
        }
    ],
    "total": 42
}
```

### Email Details

```python
{
    "id": "123456789abcdef",
    "threadId": "123456789abcdef",
    "snippet": "Preview text...",
    "date": "2025-02-10T14:30:00Z",
    "from": "sender@example.com",
    "to": ["recipient@example.com"],
    "cc": ["cc@example.com"],
    "subject": "Email Subject",
    "body": "Full email body text...",
    "html": "<div>HTML body content...</div>",
    "attachments": [
        {
            "id": "attachment123",
            "filename": "document.pdf",
            "size": 12345,
            "mimeType": "application/pdf"
        }
    ]
}
```

## API Reference

### GmailClient

```python
class GmailClient:
    """Gmail API client with OAuth2 authentication."""
    
    def __init__(self, credentials_path: str = None, token_path: str = None):
        """Initialize Gmail client with OAuth credentials."""
        
    def authorize(self) -> None:
        """Run OAuth flow and save token."""
        
    def search(self, query: str, max_results: int = 10) -> dict:
        """Search emails using Gmail search syntax."""
        
    def get_email(self, message_id: str, format: str = "full") -> dict:
        """Get email details by ID."""
        
    def send_email(self, to: str, subject: str, body: str, 
                   html: bool = False, cc: str = None, 
                   bcc: str = None) -> dict:
        """Send an email."""
        
    def create_draft(self, to: str, subject: str, body: str,
                     html: bool = False) -> str:
        """Create a draft email."""
        
    def delete_email(self, message_id: str) -> bool:
        """Permanently delete an email."""
        
    def trash_email(self, message_id: str) -> bool:
        """Move email to trash."""
```

## Troubleshooting

### "Invalid Credentials" Error

Your OAuth token may have expired. Re-run authorization:
```bash
rm ~/.nanobot/gmail/token.json
python -c "from nanobot.skills.gmail.gmail import GmailClient; GmailClient().authorize()"
```

### Quota Limits

Gmail API has quota limits:
- 250 quota units per second
- 1,000,000,000 quota units per day

If you hit quota limits, consider:
- Reducing batch sizes
- Implementing exponential backoff
- Using batch requests

### Attachments

To download attachments:
```python
email = gmail.get_email("MESSAGE_ID")
for att in email.get("attachments", []):
    gmail.download_attachment(
        "MESSAGE_ID",
        att["id"],
        f"/tmp/{att['filename']}"
    )
```

## References

- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [Gmail Search Operators](https://support.google.com/mail/answer/7190)
- [Python Gmail API Quickstart](https://developers.google.com/gmail/api/quickstart/python)
