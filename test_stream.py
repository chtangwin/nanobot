#!/usr/bin/env python3
"""Test streaming output."""

import asyncio
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

async def test():
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes['myserver']
    node = RemoteNode(node_config)

    try:
        print("\n=== Connecting ===")
        await node.setup()
        print(f"Connected: {node.is_connected}")

        print("\n=== Test 1: Non-streaming (default) ===")
        result = await node.execute("echo 'Hello from non-stream'")
        print(f"Success: {result.get('success')}")
        print(f"Output: {result.get('output')}")

        print("\n=== Test 2: Streaming ===")
        result = await node.execute("for i in 1 2 3 4 5; do echo 'Line $i'; sleep 0.2; done", stream=True)
        print(f"\nSuccess: {result.get('success')}")

        print("\n=== Test 3: Large output (no size limit) ===")
        result = await node.execute("seq 1 100", stream=True)
        print(f"Success: {result.get('success')}")
        print(f"Output length: {len(result.get('output', ''))} chars")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n=== Disconnecting ===")
        await node.teardown()
        print("Done")

if __name__ == "__main__":
    asyncio.run(test())
