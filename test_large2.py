import asyncio
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

async def test():
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes['myserver']
    node = RemoteNode(node_config)

    try:
        await node.setup()
        
        # Large output without streaming
        print("\n=== Large output (no stream, 50MB limit) ===")
        result = await node.execute("seq 1 500")
        output = result.get('output', '')
        print(f"Success: {result.get('success')}")
        print(f"Output length: {len(output)} chars")
        
    finally:
        await node.teardown()

asyncio.run(test())
