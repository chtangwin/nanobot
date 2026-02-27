#!/usr/bin/env python3
"""Test script for remote node functionality."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.nodes.config import NodeConfig, NodesConfig
from nanobot.nodes.connection import RemoteNode


async def test_config():
    """Test configuration management."""
    print("=== Testing Configuration ===")

    # Create a test config
    config = NodeConfig(
        name="test-server",
        ssh_host="user@test.example.com",
        auth_token="test-token-123",
    )

    print(f"Created config: {config.name}")
    print(f"  SSH host: {config.ssh_host}")

    # Test serialization
    data = config.to_dict()
    print(f"  Serialized: {data}")

    # Test deserialization
    config2 = NodeConfig.from_dict(data)
    print(f"  Deserialized: {config2.name}")


async def test_nodes_config():
    """Test nodes configuration management."""
    print("\n=== Testing Nodes Configuration ===")

    # Use a temporary config file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        config_file = Path(f.name)

    try:
        # Create new config
        config = NodesConfig.load(config_file)
        print(f"Created config file: {config_file}")

        # Add nodes
        config.add_node(NodeConfig(
            name="server1",
            ssh_host="user@server1.example.com",
        ))
        config.add_node(NodeConfig(
            name="server2",
            ssh_host="user@server2.example.com",
            workspace="/app",
        ))

        print(f"Added 2 nodes")

        # List nodes
        nodes = config.list_nodes()
        print(f"Nodes count: {len(nodes)}")
        for node in nodes:
            print(f"  - {node.name}: {node.ssh_host}")

        # Save and load
        config.save()
        config2 = NodesConfig.load(config_file)
        print(f"Saved and loaded config")
        print(f"  Nodes count after load: {len(config2.list_nodes())}")

    finally:
        config_file.unlink(missing_ok=True)


async def test_remote_node_config():
    """Test RemoteNode configuration (without actual connection)."""
    print("\n=== Testing RemoteNode Configuration ===")

    config = NodeConfig(
        name="test-server",
        ssh_host="user@test.example.com",
        auth_token="test-token",
    )

    node = RemoteNode(config)
    print(f"Created RemoteNode: {node.config.name}")
    print(f"  Session ID (before setup): {node.session_id}")
    print(f"  Is connected: {node.is_connected}")


async def main():
    """Run all tests."""
    print("Remote Node Test Suite\n")

    try:
        await test_config()
        await test_nodes_config()
        await test_remote_node_config()

        print("\n[OK] All tests passed!")

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
