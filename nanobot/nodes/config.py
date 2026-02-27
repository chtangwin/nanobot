"""Configuration for remote nodes."""

from dataclasses import dataclass, field
from typing import Dict, Optional
from pathlib import Path
import json
import os


@dataclass
class NodeConfig:
    """Configuration for a single remote node."""

    name: str
    ssh_host: str  # user@host format
    ssh_port: int = 22
    ssh_key_path: Optional[str] = None
    remote_port: int = 8765  # WebSocket server port on remote
    local_port: Optional[int] = None  # Local port for SSH tunnel (auto-assigned if None)
    auth_token: Optional[str] = None  # Token for authentication
    workspace: Optional[str] = None  # Default workspace on remote

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "ssh_host": self.ssh_host,
            "ssh_port": self.ssh_port,
            "ssh_key_path": self.ssh_key_path,
            "remote_port": self.remote_port,
            "local_port": self.local_port,
            "auth_token": self.auth_token,
            "workspace": self.workspace,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NodeConfig":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class NodesConfig:
    """Configuration for all nodes."""

    nodes: Dict[str, NodeConfig] = field(default_factory=dict)
    config_file: Optional[Path] = None

    def add_node(self, config: NodeConfig) -> None:
        """Add a node configuration."""
        self.nodes[config.name] = config

    def remove_node(self, name: str) -> None:
        """Remove a node configuration."""
        self.nodes.pop(name, None)

    def get_node(self, name: str) -> Optional[NodeConfig]:
        """Get a node configuration by name."""
        return self.nodes.get(name)

    def list_nodes(self) -> list[NodeConfig]:
        """List all node configurations."""
        return list(self.nodes.values())

    def save(self) -> None:
        """Save configuration to file."""
        if self.config_file:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "nodes": {name: config.to_dict() for name, config in self.nodes.items()}
            }
            self.config_file.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, config_file: Path) -> "NodesConfig":
        """Load configuration from file."""
        if not config_file.exists() or config_file.stat().st_size == 0:
            config = cls(config_file=config_file)
            config.save()
            return config

        data = json.loads(config_file.read_text())
        nodes = {
            name: NodeConfig.from_dict(node_data)
            for name, node_data in data.get("nodes", {}).items()
        }
        return cls(nodes=nodes, config_file=config_file)

    @classmethod
    def get_default_config_path(cls) -> Path:
        """Get default configuration file path."""
        config_dir = Path(os.environ.get("NANOBOT_CONFIG_DIR", 
                                        Path.home() / ".nanobot"))
        return config_dir / "nodes.json"
