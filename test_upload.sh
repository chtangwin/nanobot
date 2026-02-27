#!/bin/bash
# Test SSH stdin upload manually

SSH_HOST="root@10.0.0.174"
SESSION_ID="test-upload"
REMOTE_DIR="/tmp/$SESSION_ID"

echo "=== Testing SSH stdin upload ==="
echo ""

# Step 1: Create directory
echo "[1] Creating remote directory: $REMOTE_DIR"
ssh $SSH_HOST "mkdir -p $REMOTE_DIR"
echo ""

# Step 2: Upload script via stdin
echo "[2] Uploading node_server.py via stdin"
cat nanobot/nodes/node_server.py | ssh $SSH_HOST "cat > $REMOTE_DIR/node_server.py"
echo "Done"
echo ""

# Step 3: Verify
echo "[3] Verifying file size"
ssh $SSH_HOST "wc -c $REMOTE_DIR/node_server.py"
echo ""

# Step 4: Upload config
echo "[4] Uploading config.json"
echo '{"port": 8765, "tmux": true}' | ssh $SSH_HOST "cat > $REMOTE_DIR/config.json"
echo "Done"
echo ""

# Step 5: Verify config
echo "[5] Verifying config.json"
ssh $SSH_HOST "cat $REMOTE_DIR/config.json"
echo ""

# Step 6: Start node
echo "[6] Starting node server in background"
ssh $SSH_HOST "cd $REMOTE_DIR && nohup uv run --with websockets node_server.py --config config.json > $REMOTE_DIR/node_server.log 2>&1 &"
echo "Done"
echo ""

# Step 7: Wait
echo "[7] Waiting 3 seconds..."
sleep 3
echo ""

# Step 8: Check processes
echo "[8] Checking for uv processes"
ssh $SSH_HOST "pgrep -a uv" || echo "No uv processes found"
echo ""

# Step 9: Check log
echo "[9] Checking log file"
ssh $SSH_HOST "cat $REMOTE_DIR/node_server.log" || echo "Log not found"
echo ""

# Step 10: Check tmux
echo "[10] Checking tmux sessions"
ssh $SSH_HOST "tmux ls" || echo "No tmux sessions"
echo ""

echo "=== Test complete ==="
