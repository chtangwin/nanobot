#!/usr/bin/env python3
"""Detailed test of remote node execution."""

import asyncio
import logging
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

async def test():
    # Load config
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes['myserver']

    print("=" * 60)
    print("Testing Remote Node Execution")
    print("=" * 60)

    # Create node
    node = RemoteNode(node_config)

    try:
        # Connect
        print("\n[1] Connecting...")
        await node.setup()
        print(f"Connected: {node.is_connected}")

        # Execute command
        print("\n[2] Executing: pwd")
        result = await node.execute("pwd")
        print(f"Result type: {type(result)}")
        print(f"Result: {result}")

        # Execute another command
        print("\n[3] Executing: whoami")
        result2 = await node.execute("whoami")
        print(f"Result type: {type(result2)}")
        print(f"Result: {result2}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[4] Disconnecting...")
        await node.teardown()
        print("Done")

if __name__ == "__main__":
    asyncio.run(test())
