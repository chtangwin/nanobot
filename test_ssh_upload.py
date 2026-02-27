#!/usr/bin/env python3
"""Test new deployment method with stdin upload."""

import asyncio
import subprocess
import sys

from nanobot.nodes.connection import _get_node_script_path, _NODE_SCRIPT

async def test_ssh_upload():
    """Test SSH stdin upload."""
    
    ssh_host = "root@10.0.0.174"
    ssh_port = "22"
    session_id = "test-upload"
    remote_dir = f"/tmp/{session_id}"
    
    print("=" * 60)
    print("Testing SSH stdin Upload Method")
    print("=" * 60)
    
    # Step 1: Create directory
    print(f"\n[Step 1] Creating remote directory: {remote_dir}")
    cmd = ["ssh", "-p", ssh_port, ssh_host, f"mkdir -p {remote_dir}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    if result.stdout:
        print(f"Stdout: {result.stdout}")
    if result.stderr:
        print(f"Stderr: {result.stderr}")
    
    # Step 2: Upload script via stdin
    print(f"\n[Step 2] Uploading node_server.py via stdin")
    print(f"Script size: {len(_NODE_SCRIPT)} bytes")
    
    cmd = ["ssh", "-p", ssh_port, ssh_host, f"cat > {remote_dir}/node_server.py"]
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False  # Use bytes
    )
    
    stdout, stderr = process.communicate(_NODE_SCRIPT.encode())
    print(f"Return code: {process.returncode}")
    if stderr:
        print(f"Stderr: {stderr.decode()}")
    else:
        print("OK - Upload successful")
    
    # Step 3: Verify script
    print(f"\n[Step 3] Verifying script exists")
    cmd = ["ssh", "-p", ssh_port, ssh_host, f"wc -l {remote_dir}/node_server.py"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Lines: {result.stdout.strip()}")
    
    # Step 4: Check file size
    cmd = ["ssh", "-p", ssh_port, ssh_host, f"wc -c {remote_dir}/node_server.py"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Size: {result.stdout.strip()}")
    
    # Step 5: Upload config
    print(f"\n[Step 4] Uploading config.json")
    config_json = '{"port": 8765, "tmux": true}'
    cmd = ["ssh", "-p", ssh_port, ssh_host, f"cat > {remote_dir}/config.json"]
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False
    )
    
    stdout, stderr = process.communicate(config_json.encode())
    print(f"Return code: {process.returncode}")
    if stderr:
        print(f"Stderr: {stderr.decode()}")
    else:
        print("OK Config uploaded")
    
    # Step 6: Verify config
    print(f"\n[Step 5] Verifying config.json")
    cmd = ["ssh", "-p", ssh_port, ssh_host, f"cat {remote_dir}/config.json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Content:\n{result.stdout}")
    
    # Step 7: Try to start node
    print(f"\n[Step 6] Starting node server")
    start_cmd = f"cd {remote_dir} && uv run --with websockets node_server.py --config config.json > {remote_dir}/node_server.log 2>&1 &"
    cmd = ["ssh", "-p", ssh_port, ssh_host, start_cmd]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    if result.stdout:
        print(f"Stdout: {result.stdout}")
    if result.stderr:
        print(f"Stderr: {result.stderr}")
    
    # Step 8: Wait
    print(f"\n[Step 7] Waiting 3 seconds...")
    await asyncio.sleep(3)
    
    # Step 9: Check processes
    print(f"\n[Step 8] Checking for uv processes")
    cmd = ["ssh", "-p", ssh_port, ssh_host, "pgrep -a uv"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(f"Processes:\n{result.stdout}")
    else:
        print("(no uv processes found)")
    
    # Step 10: Check log
    print(f"\n[Step 9] Checking node_server.log")
    cmd = ["ssh", "-p", ssh_port, ssh_host, f"cat {remote_dir}/node_server.log"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(f"Log:\n{result.stdout}")
    else:
        print("(log empty or not found)")
    
    # Step 11: Check tmux
    print(f"\n[Step 10] Checking tmux sessions")
    cmd = ["ssh", "-p", ssh_port, ssh_host, "tmux ls"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(f"Sessions:\n{result.stdout}")
    else:
        print("(no tmux sessions)")

if __name__ == "__main__":
    asyncio.run(test_ssh_upload())
