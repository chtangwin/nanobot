#!/usr/bin/env python3
"""Quick test of remote node connection."""

import asyncio
import logging
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

async def test():
    # Load config
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes['myserver']

    print("=" * 60)
    print("Testing Remote Node Connection")
    print("=" * 60)
    print(f"Node: {node_config.name}")
    print(f"Host: {node_config.ssh_host}")
    print()

    # Create node
    node = RemoteNode(node_config)

    try:
        # Connect
        print("\n[1] Connecting to node...")
        await node.setup()
        print(f"OK - Connected: {node.is_connected}")

        # Execute command
        print("\n[2] Executing command: pwd")
        result = await node.execute("pwd")
        print(f"Result:\n{result['output']}")

        # Execute another command
        print("\n[3] Executing command: whoami")
        result = await node.execute("whoami")
        print(f"Result:\n{result['output']}")

        # Get log
        print("\n[4] Remote server log:")
        log = await node._get_remote_log(tail_lines=10)
        print(log)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Disconnect
        print("\n[5] Disconnecting...")
        await node.teardown()
        print("OK - Disconnected")

if __name__ == "__main__":
    asyncio.run(test())
