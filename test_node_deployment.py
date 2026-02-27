"""Test node deployment manually."""
import asyncio
import logging
from nanobot.nodes.manager import NodeManager
from nanobot.nodes.config import NodesConfig

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def test():
    config = NodesConfig.load(NodesConfig.get_default_config_path())
    manager = NodeManager(config)
    
    print("\n=== Testing Node Deployment ===\n")
    print(f"Config: {config.nodes}")
    
    try:
        print("\n1. Connecting to myserver...")
        node = await manager.connect("myserver")
        print(f"✓ Connected: session_id={node.session_id}")
        print(f"✓ is_connected: {node.is_connected}")
        
        # Wait a bit
        await asyncio.sleep(2)
        
        print("\n2. Executing test command...")
        result = await node.execute("echo 'Hello from remote'", timeout=10)
        print(f"Success: {result['success']}")
        print(f"Output: {result['output']}")
        
        print("\n3. Disconnecting...")
        await manager.disconnect("myserver")
        print("✓ Disconnected")
        
    except Exception as e:
        print(f"\n✗ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test())
