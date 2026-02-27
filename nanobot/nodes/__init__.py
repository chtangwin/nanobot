"""Remote node management for nanobot.

This module provides the ability to execute commands on remote machines
through SSH tunnels and WebSocket connections, with zero installation
requirements on the remote side.
"""

from nanobot.nodes.connection import RemoteNode
from nanobot.nodes.manager import NodeManager
from nanobot.nodes.config import NodeConfig

__all__ = ["RemoteNode", "NodeManager", "NodeConfig"]
