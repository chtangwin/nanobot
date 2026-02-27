import asyncio
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

async def test():
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes['myserver']
    node = RemoteNode(node_config)

    try:
        await node.setup()
        
        # Test large output
        print("\n=== Large output (streaming) ===")
        result = await node.execute("seq 1 500", stream=True)
        output = result.get('output', '')
        print(f"Output length: {len(output)} chars")
        print(f"First 50 chars: {output[:50]}")
        print(f"Last 50 chars: {output[-50:]}")
        
    finally:
        await node.teardown()

asyncio.run(test())
