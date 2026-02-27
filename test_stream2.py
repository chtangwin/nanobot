import asyncio
from nanobot.nodes.config import NodesConfig
from nanobot.nodes.connection import RemoteNode

async def test():
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    node_config = config.nodes['myserver']
    node = RemoteNode(node_config)

    try:
        await node.setup()
        
        # Test streaming with a simple echo
        print("\n=== Streaming echo ===")
        result = await node.execute("echo hello world", stream=True)
        print(f"Output: '{result.get('output')}'")
        
        # Test non-streaming
        print("\n=== Non-streaming echo ===")
        result = await node.execute("echo hello world")
        print(f"Output: '{result.get('output')}'")
        
    finally:
        await node.teardown()

asyncio.run(test())
