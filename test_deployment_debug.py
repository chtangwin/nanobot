#!/usr/bin/env python3
"""Test remote node deployment manually."""

import asyncio
import json
import base64
import subprocess
import sys

from nanobot.nodes.connection import _get_node_script_path, _NODE_SCRIPT

async def test_deployment():
    """Test deployment step by step."""
    
    # Node configuration
    ssh_host = "root@10.0.0.174"
    session_id = "test-deploy"
    remote_dir = f"/tmp/{session_id}"
    
    print("=" * 60)
    print("Testing Remote Node Deployment")
    print("=" * 60)
    
    # Step 1: Create directory
    print(f"\n[Step 1] Creating remote directory: {remote_dir}")
    cmd = f"ssh {ssh_host} 'mkdir -p {remote_dir}'"
    print(f"Command: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    if result.stdout:
        print(f"Stdout: {result.stdout}")
    if result.stderr:
        print(f"Stderr: {result.stderr}")
    
    # Step 2: Upload script
    print(f"\n[Step 2] Uploading node_server.py")
    script = _NODE_SCRIPT
    encoded_script = base64.b64encode(script.encode()).decode()
    
    cmd = f"ssh {ssh_host} 'echo {encoded_script} | base64 -d > {remote_dir}/node_server.py'"
    print(f"Command length: {len(cmd)} (truncated)")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    if result.returncode != 0 and result.stderr:
        print(f"Stderr: {result.stderr[:500]}")
    else:
        print("✓ Script uploaded")
    
    # Step 3: Verify script
    print(f"\n[Step 3] Verifying script exists")
    cmd = f"ssh {ssh_host} 'ls -la {remote_dir}/node_server.py'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Output:\n{result.stdout}")
    
    # Step 4: Upload config
    print(f"\n[Step 4] Uploading config.json")
    config = {"port": 8765, "tmux": True}
    config_json = json.dumps(config, indent=2)
    encoded_config = base64.b64encode(config_json.encode()).decode()
    
    cmd = f"ssh {ssh_host} 'echo {encoded_config} | base64 -d > {remote_dir}/config.json'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    if result.returncode != 0 and result.stderr:
        print(f"Stderr: {result.stderr[:500]}")
    else:
        print("✓ Config uploaded")
    
    # Step 5: Verify config
    print(f"\n[Step 5] Verifying config.json")
    cmd = f"ssh {ssh_host} 'cat {remote_dir}/config.json'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Content:\n{result.stdout}")
    
    # Step 6: Check for uv
    print(f"\n[Step 6] Checking for uv on remote")
    cmd = f"ssh {ssh_host} 'which uv'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    if result.returncode == 0:
        print(f"✓ uv found: {result.stdout.strip()}")
    else:
        print("✗ uv NOT found!")
        cmd = f"ssh {ssh_host} 'which python3'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ python3 found: {result.stdout.strip()}")
        else:
            print("✗ python3 NOT found!")
    
    # Step 7: Try to start node manually
    print(f"\n[Step 7] Starting node server manually")
    cmd = f"ssh {ssh_host} 'cd {remote_dir} && uv run --with websockets node_server.py --config config.json > node_server.log 2>&1 &'"
    print(f"Command: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    if result.stdout:
        print(f"Stdout: {result.stdout}")
    if result.stderr:
        print(f"Stderr: {result.stderr[:500]}")
    
    # Step 8: Wait and check
    print(f"\n[Step 8] Waiting 3 seconds...")
    await asyncio.sleep(3)
    
    # Step 9: Check for processes
    print(f"\n[Step 9] Checking for uv processes")
    cmd = f"ssh {ssh_host} 'pgrep -a uv'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Output: {result.stdout if result.stdout else '(no processes)'}")
    
    print(f"\n[Step 10] Checking for tmux sessions")
    cmd = f"ssh {ssh_host} 'tmux ls'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Output: {result.stdout if result.stdout else '(no sessions)'}")
    
    # Step 11: Check log
    print(f"\n[Step 11] Checking node_server.log")
    cmd = f"ssh {ssh_host} 'cat {remote_dir}/node_server.log'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout:
        print(f"Log content:\n{result.stdout}")
    else:
        print(f"Log file empty or not found")

if __name__ == "__main__":
    asyncio.run(test_deployment())
