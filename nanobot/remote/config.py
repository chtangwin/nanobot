"""Configuration for remote hosts."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
import json
import os


@dataclass
class HostConfig:
    """Configuration for a single remote host."""

    name: str
    ssh_host: str  # user@host format
    ssh_port: int = 22
    ssh_key_path: Optional[str] = None
    remote_port: int = 8765  # WebSocket server port on remote
    local_port: Optional[int] = None  # Local port for SSH tunnel
    auth_token: Optional[str] = None
    workspace: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ssh_host": self.ssh_host,
            "ssh_port": self.ssh_port,
            "ssh_key_path": self.ssh_key_path,
            "remote_port": self.remote_port,
            "local_port": self.local_port,
            "auth_token": self.auth_token,
            "workspace": self.workspace,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "HostConfig":
        return cls(name=name, **data)


@dataclass
class HostsConfig:
    """Configuration for all remote hosts."""

    hosts: Dict[str, HostConfig] = field(default_factory=dict)
    config_file: Optional[Path] = None

    def add_host(self, config: HostConfig) -> None:
        self.hosts[config.name] = config

    def remove_host(self, name: str) -> None:
        self.hosts.pop(name, None)

    def get_host(self, name: str) -> Optional[HostConfig]:
        return self.hosts.get(name)

    def list_hosts(self) -> list[HostConfig]:
        return list(self.hosts.values())

    def save(self) -> None:
        if self.config_file:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"hosts": {name: cfg.to_dict() for name, cfg in self.hosts.items()}}
            self.config_file.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, config_file: Path) -> "HostsConfig":
        if not config_file.exists() or config_file.stat().st_size == 0:
            cfg = cls(config_file=config_file)
            cfg.save()
            return cfg

        data = json.loads(config_file.read_text())
        raw_hosts = data.get("hosts") or {}
        hosts = {name: HostConfig.from_dict(name, item) for name, item in raw_hosts.items()}
        return cls(hosts=hosts, config_file=config_file)

    @classmethod
    def get_default_config_path(cls) -> Path:
        config_dir = Path(os.environ.get("NANOBOT_CONFIG_DIR", Path.home() / ".nanobot"))
        return config_dir / "hosts.json"
