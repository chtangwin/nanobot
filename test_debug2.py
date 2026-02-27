#!/usr/bin/env python3
"""Detailed test with more debug output."""

import asyncio
import logging
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

logging.basicConfig(level=logging.INFO)

async def test():
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes['myserver']

    node = RemoteNode(node_config)

    try:
        print("\n[1] Connecting...")
        await node.setup()
        print(f"Connected: {node.is_connected}")

        print("\n[2] Executing: pwd")
        result = await node.execute("pwd")
        print(f"Success: {result.get('success')}")
        print(f"Output: '{result.get('output')}'")
        print(f"Error: {result.get('error')}")

        print("\n[3] Executing: whoami")
        result2 = await node.execute("whoami")
        print(f"Success: {result2.get('success')}")
        print(f"Output: '{result2.get('output')}'")
        
        print("\n[4] Executing: ls -la")
        result3 = await node.execute("ls -la")
        print(f"Success: {result3.get('success')}")
        print(f"Output: '{result3.get('output')}'")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[5] Disconnecting...")
        await node.teardown()
        print("Done")

if __name__ == "__main__":
    asyncio.run(test())
