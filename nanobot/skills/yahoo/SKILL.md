---
name: yahoo
description: Access Yahoo Mail via IMAP/SMTP - read, send, move, and delete emails.
homepage: https://help.yahoo.com/kb/pop-settings-sln4724.html
metadata: {"nanobot":{"emoji":"📬","requires":{"pypi":[]}}}
---

# Yahoo Mail

Interact with Yahoo Mail via IMAP and SMTP protocols. Uses built-in Python libraries (no pip install needed).

## Setup

### 1. Enable App Password (Required!)

Yahoo requires an **App Password** for third-party access (not your regular password):

1. Go to [Yahoo Account Security](https://login.yahoo.com/account/security)
2. Enable **Two-step verification** if not already enabled
3. Click **Generate app password** or **App passwords**
4. Select app name: `nanobot`
5. Copy the generated 16-character password

### 2. Create Config File

Create the config file at `~/.nanobot/yahoo/config.json`:

```json
{
  "username": "your_email@yahoo.com",
  "app_password": "your-16-char-app-password"
}
```

Or run the setup helper:

```bash
cd C:\Dev_Home\dev_cc\nanobot
uv run python -c "from nanobot.skills.yahoo.yahoo import YahooClient; YahooClient().setup()"
```

### 3. No pip install needed!

This skill uses built-in Python packages:
- `imaplib` - IMAP protocol
- `smtplib` - SMTP protocol  
- `email` - Email parsing
- `ssl` - Secure connections

## Usage Examples

### Initialize Client

```python
from nanobot.skills.yahoo.yahoo import YahooClient

# Auto-load from config file
yahoo = YahooClient()

# Or provide credentials directly
yahoo = YahooClient(
    username="your_email@yahoo.com",
    app_password="your-app-password"
)

# Connect
yahoo.connect()
```

### List Folders

```python
folders = yahoo.list_folders()
# Returns: ['INBOX', 'Sent', 'Drafts', 'Archive', 'Trash', 'Spam', 'Work', ...]
```

### Search Emails

```python
# Search unread emails
emails = yahoo.search("UNSEEN")

# Search from specific sender
emails = yahoo.search('FROM "boss@company.com"')

# Search by subject
emails = yahoo.search('SUBJECT "meeting"')

# Search in date range
emails = yahoo.search('SINCE 01-Feb-2025 BEFORE 10-Feb-2025')

# Combine criteria
emails = yahoo.search('UNSEEN FROM "boss@company.com"')

# Limit results
emails = yahoo.search("ALL", limit=20)
```

### Read Email

```python
# Get email by ID
email = yahoo.get_email(message_id)

# Access email fields
print(email["subject"])
print(email["from"])
print(email["to"])
print(email["date"])
print(email["body"])

# Check for attachments
if email["attachments"]:
    for att in email["attachments"]:
        print(f"Attachment: {att['filename']} ({att['size']} bytes)")
```

### Send Email

```python
# Simple text email
yahoo.send_email(
    to="recipient@example.com",
    subject="Hello from Yahoo!",
    body="This is a test email from nanobot."
)

# HTML email
yahoo.send_email(
    to="recipient@example.com",
    subject="HTML Email",
    body="<h1>Hello</h1><p>This is <b>HTML</b> content.</p>",
    html=True
)

# With CC and BCC
yahoo.send_email(
    to="recipient@example.com",
    cc="cc@example.com",
    bcc="bcc@example.com",
    subject="Meeting Reminder",
    body="Don't forget our meeting tomorrow."
)
```

### Move Email to Folder

```python
# Move to a folder
yahoo.move_email(message_id, "Work")

# Archive (remove from INBOX)
yahoo.archive_email(message_id)

# Unarchive (move back to INBOX)
yahoo.unarchive_email(message_id)
```

### Delete Email

```python
# Move to Trash
yahoo.delete_email(message_id)

# Permanently delete (from Trash)
yahoo.permanently_delete(message_id)
```

### Create Folder

```python
# Create a new folder
yahoo.create_folder("Projects")
```

### Download Attachment

```python
email = yahoo.get_email(message_id)
for att in email["attachments"]:
    yahoo.download_attachment(
        message_id,
        att["id"],
        f"C:/Downloads/{att['filename']}"
    )
```

### Disconnect

```python
# Always disconnect when done
yahoo.disconnect()
```

### Context Manager (Auto-connect/disconnect)

```python
with YahooClient() as yahoo:
    emails = yahoo.search("UNSEEN")
    for email in emails:
        print(email["subject"])
```

## IMAP Search Criteria

Yahoo Mail supports standard IMAP SEARCH criteria:

| Criteria | Description | Example |
|----------|-------------|---------|
| `ALL` | All emails | `search("ALL")` |
| `UNSEEN` | Unread emails | `search("UNSEEN")` |
| `SEEN` | Read emails | `search("SEEN")` |
| `FLAGGED` | Starred emails | `search("FLAGGED")` |
| `FROM` | Sender | `search('FROM "john"')` |
| `TO` | Recipient | `search('TO "me"')` |
| `SUBJECT` | Subject contains | `search('SUBJECT "report"')` |
| `BODY` | Body contains | `search('BODY "urgent"')` |
| `SINCE` | After date | `search('SINCE 01-Feb-2025')` |
| `BEFORE` | Before date | `search('BEFORE 10-Feb-2025')` |
| `ON` | Specific date | `search('ON 05-Feb-2025')` |
| `LARGER` | Size > bytes | `search('LARGER 10000')` |
| `SMALLER` | Size < bytes | `search('SMALLER 5000')` |

Combine criteria:
```python
# Unread from boss since Feb 1
yahoo.search('UNSEEN FROM "boss@company.com" SINCE 01-Feb-2025')
```

## Return Format

### Search Results

```python
[
    {
        "id": "1234",
        "subject": "Meeting Tomorrow",
        "from": "sender@example.com",
        "to": ["your_email@yahoo.com"],
        "date": "2025-02-10T14:30:00",
        "flags": ["\\Seen"],
        "folder": "INBOX",
        "size": 5432,
        "has_attachment": True
    },
    ...
]
```

### Email Details

```python
{
    "id": "1234",
    "subject": "Meeting Tomorrow",
    "from": "Sender Name <sender@example.com>",
    "to": ["your_email@yahoo.com"],
    "cc": [],
    "date": "2025-02-10T14:30:00",
    "body": "Full email body text...",
    "html": "<div>HTML body content...</div>",
    "flags": ["\\Seen"],
    "folder": "INBOX",
    "attachments": [
        {
            "id": "1",
            "filename": "document.pdf",
            "size": 12345,
            "mime_type": "application/pdf"
        }
    ]
}
```

## API Reference

### YahooClient

```python
class YahooClient:
    """Yahoo Mail client using IMAP and SMTP."""
    
    def __init__(self, username: str = None, app_password: str = None):
        """Initialize Yahoo Mail client."""
        
    def setup(self) -> None:
        """Interactive setup to create config file."""
        
    def connect(self) -> bool:
        """Connect to IMAP and SMTP servers."""
        
    def disconnect(self) -> None:
        """Disconnect from servers."""
        
    def list_folders(self) -> list[str]:
        """List all email folders."""
        
    def search(self, criteria: str = "ALL", folder: str = "INBOX", 
               limit: int = 50) -> list[dict]:
        """Search emails using IMAP criteria."""
        
    def get_email(self, message_id: str, folder: str = "INBOX") -> dict:
        """Get full email details by ID."""
        
    def send_email(self, to: str, subject: str, body: str,
                   html: bool = False, cc: str = None, 
                   bcc: str = None) -> bool:
        """Send an email via SMTP."""
        
    def move_email(self, message_id: str, dest_folder: str,
                   source_folder: str = "INBOX") -> bool:
        """Move email to another folder."""
        
    def archive_email(self, message_id: str) -> bool:
        """Archive email (move to Archive folder)."""
        
    def unarchive_email(self, message_id: str) -> bool:
        """Unarchive email (move to INBOX)."""
        
    def delete_email(self, message_id: str, folder: str = "INBOX") -> bool:
        """Move email to Trash."""
        
    def permanently_delete(self, message_id: str) -> bool:
        """Permanently delete email from Trash."""
        
    def create_folder(self, folder_name: str) -> bool:
        """Create a new folder."""
        
    def download_attachment(self, message_id: str, attachment_id: str,
                           save_path: str, folder: str = "INBOX") -> bool:
        """Download an attachment."""
```

## Yahoo Mail Server Settings

| Protocol | Server | Port | Security |
|----------|--------|------|----------|
| **IMAP** | `imap.mail.yahoo.com` | 993 | SSL/TLS |
| **SMTP** | `smtp.mail.yahoo.com` | 465 | SSL/TLS |
| **POP3** | `pop.mail.yahoo.com` | 995 | SSL/TLS |

## Troubleshooting

### "Authentication failed" Error

1. Make sure you're using an **App Password**, not your regular password
2. Regenerate the app password at [Yahoo Account Security](https://login.yahoo.com/account/security)
3. Check that 2FA is enabled

### "Connection refused" Error

1. Check your internet connection
2. Verify Yahoo Mail IMAP access is enabled in Yahoo settings
3. Some networks block IMAP ports - try a different network

### Search Not Finding Emails

1. IMAP SEARCH is case-insensitive for most criteria
2. Use quotes for multi-word searches: `'SUBJECT "meeting notes"'`
3. Date format must be: `DD-MMM-YYYY` (e.g., `01-Feb-2025`)

### Folder Names

Yahoo folder names may differ from what you see in webmail:
- `INBOX` - Inbox
- `Sent` - Sent items
- `Drafts` - Draft messages
- `Archive` - Archived emails
- `Trash` - Deleted emails
- `Bulk` or `Spam` - Spam folder

## Differences from Gmail

| Feature | Gmail | Yahoo |
|---------|-------|-------|
| Labels | Multiple per email | Single folder |
| Search | Gmail search operators | IMAP SEARCH only |
| Archive | "All Mail" | "Archive" folder |
| OAuth2 | Built-in | App Password only |
| API | REST API | IMAP/SMTP only |

## References

- [Yahoo Mail IMAP Settings](https://help.yahoo.com/kb/pop-settings-sln4724.html)
- [Yahoo App Passwords](https://help.yahoo.com/kb/generate-app-password-sln15241.html)
- [Python IMAP Library](https://docs.python.org/3/library/imaplib.html)
- [Python SMTP Library](https://docs.python.org/3/library/smtplib.html)
