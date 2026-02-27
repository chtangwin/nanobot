"""Yahoo Mail Client for Nanobot"""
import imaplib
import smtplib
import ssl
import json
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional, List, Dict, Any

IMAP_SERVER = "imap.mail.yahoo.com"
IMAP_PORT = 993
SMTP_SERVER = "smtp.mail.yahoo.com"
SMTP_PORT = 465

CONFIG_DIR = Path.home() / ".nanobot" / "yahoo"
CONFIG_FILE = CONFIG_DIR / "config.json"

class YahooClient:
    """Yahoo Mail IMAP/SMTP client."""

    def __init__(self, username: Optional[str] = None, app_password: Optional[str] = None):
        self.username = username
        self.app_password = app_password
        self.imap_client = None
        self.smtp_client = None
        self._connected = False
        if not self.username or not self.app_password:
            self._load_config()

    @staticmethod
    def setup() -> None:
        """Interactive setup for Yahoo Mail credentials."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        if CONFIG_FILE.exists():
            overwrite = input(f"Config exists at {CONFIG_FILE}. Overwrite? (y/N): ")
            if overwrite.lower() != "y":
                print("Setup cancelled.")
                return

        print("\n=== Yahoo Mail Setup ===")
        print("1. Go to https://login.yahoo.com/account/security")
        print("2. Enable Two-step verification (if not enabled)")
        print("3. Click 'Generate app password'")
        print("4. Select app name: 'nanobot'")
        print("5. Copy the 16-character password\n")

        username = input("Enter your Yahoo email address: ").strip()
        app_password = input("Enter your Yahoo App Password: ").strip()

        if not username or not app_password:
            print("❌ Username and app password are required!")
            return

        config = {"username": username, "app_password": app_password}

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Credentials saved to {CONFIG_FILE}")
        print("✅ Setup complete! Testing connection...")

        # Test connection
        try:
            client = YahooClient(username, app_password)
            client.connect()
            folders = client.list_folders()
            print(f"✅ Successfully connected! Found {len(folders)} folders.")
            print(f"   Folders: {folders}")
            client.disconnect()
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            print("Please check your credentials and try again.")

    def _load_config(self) -> None:
        if not CONFIG_FILE.exists():
            raise FileNotFoundError("Run setup() first")
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.username = self.username or config.get("username")
        self.app_password = self.app_password or config.get("app_password")

    def connect(self) -> bool:
        if self._connected: return True
        context = ssl.create_default_context()
        self.imap_client = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT, ssl_context=context)
        self.imap_client.login(self.username, self.app_password)
        self.smtp_client = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context)
        self.smtp_client.login(self.username, self.app_password)
        self._connected = True
        return True

    def disconnect(self) -> None:
        if self.imap_client:
            try: self.imap_client.close(); self.imap_client.logout()
            except: pass
        if self.smtp_client:
            try: self.smtp_client.quit()
            except: pass
        self._connected = False

    def __enter__(self): self.connect(); return self
    def __exit__(self, *args): self.disconnect()

    def list_folders(self) -> List[str]:
        if not self._connected: self.connect()
        _, folders = self.imap_client.list()
        names = []
        for f in folders:
            parts = f.decode() if isinstance(f, bytes) else f
            if '"' in parts:
                names.append(parts.split('"')[-2])
        return names

    def select_folder(self, folder: str = "INBOX") -> bool:
        if not self._connected: self.connect()
        self.imap_client.select(folder, readonly=False)
        return True

    def create_folder(self, folder_name: str) -> bool:
        if not self._connected: self.connect()
        try: self.imap_client.create(folder_name)
        except: pass
        return True

    def search(self, criteria: str = "ALL", folder: str = "INBOX", limit: int = 50) -> List[Dict]:
        if not self._connected: self.connect()
        self.select_folder(folder)
        status, ids = self.imap_client.search(None, criteria)
        if status != "OK" or not ids[0]: return []
        msg_ids = ids[0].split()[-limit:] if limit else ids[0].split()
        results = []
        for msg_id in reversed(msg_ids):
            try:
                _, data = self.imap_client.fetch(msg_id, "(RFC822.HEADER)")
                msg = email.message_from_bytes(data[0][1])
                results.append({
                    "id": msg_id.decode(),
                    "subject": msg.get("Subject", ""),
                    "from": msg.get("From", ""),
                    "date": msg.get("Date", ""),
                    "folder": folder
                })
            except: pass
        return results

    def get_email(self, message_id: str, folder: str = "INBOX") -> Dict:
        if not self._connected: self.connect()
        self.select_folder(folder)
        _, data = self.imap_client.fetch(message_id, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        result = {
            "id": message_id,
            "subject": msg.get("Subject", ""),
            "from": msg.get("From", ""),
            "to": msg.get("To", ""),
            "body": "",
            "html": "",
            "attachments": []
        }
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    result["body"] = payload.decode("utf-8", errors="replace") or ""
            elif ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    result["html"] = payload.decode("utf-8", errors="replace") or ""
            elif "attachment" in str(part.get("Content-Disposition", "")):
                fn = part.get_filename()
                if fn:
                    result["attachments"].append({"filename": fn})
        return result

    def send_email(self, to: str, subject: str, body: str, html: bool = False, cc: str = None, bcc: str = None) -> bool:
        if not self._connected: self.connect()
        if html:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.username
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        self.smtp_client.send_message(msg)
        return True

    def move_email(self, message_id: str, dest_folder: str, source_folder: str = "INBOX") -> bool:
        if not self._connected: self.connect()
        self.select_folder(source_folder)
        try:
            self.imap_client.move(message_id, dest_folder)
        except:
            self.imap_client.copy(message_id, dest_folder)
            self.imap_client.store(message_id, "+FLAGS", "\\Deleted")
            self.imap_client.expunge()
        return True

    def archive_email(self, message_id: str, source_folder: str = "INBOX") -> bool:
        return self.move_email(message_id, "Archive", source_folder)

    def unarchive_email(self, message_id: str) -> bool:
        return self.move_email(message_id, "INBOX", "Archive")

    def delete_email(self, message_id: str, folder: str = "INBOX") -> bool:
        return self.move_email(message_id, "Trash", folder)

    def permanently_delete(self, message_id: str) -> bool:
        if not self._connected: self.connect()
        self.select_folder("Trash")
        self.imap_client.store(message_id, "+FLAGS", "\\Deleted")
        self.imap_client.expunge()
        return True

    def download_attachment(self, message_id: str, attachment_id: str, save_path: str, folder: str = "INBOX") -> bool:
        if not self._connected: self.connect()
        self.select_folder(folder)
        _, data = self.imap_client.fetch(message_id, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        for part in msg.walk():
            fn = part.get_filename()
            if fn and (fn == attachment_id or part.get("Content-Id") == attachment_id):
                payload = part.get_payload(decode=True)
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(payload)
                return True
        return False