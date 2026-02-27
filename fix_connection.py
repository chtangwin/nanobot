#!/usr/bin/env python3
"""Fix connection.py by adding _ssh_upload method."""

import re

# Read the file
with open('nanobot/nodes/connection.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the _ssh_exec method and add _ssh_upload before it
ssh_upload_method = '''    async def _ssh_upload(self, content: str, remote_path: str):
        """Upload content to a file on remote server via SSH stdin."""
        ssh_cmd = [
            "ssh",
            "-p", str(self.config.ssh_port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
        ]

        if self.config.ssh_key_path:
            ssh_cmd.extend(["-i", self.config.ssh_key_path])

        ssh_cmd.extend([self.config.ssh_host, f"cat > {remote_path}"])

        process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate(content.encode())

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to upload file to {remote_path}: {error_msg}")

'''

# Insert _ssh_upload before _ssh_exec
pattern = r'(    async def _ssh_exec\(self, command: str\) -> str:)'
replacement = ssh_upload_method + r'\1'
content = re.sub(pattern, replacement, content)

# Fix _deploy_node to use _ssh_upload instead of base64
old_deploy = '''        # Upload script (base64 encoded to avoid shell escaping issues)
        logger.info(f"Uploading node_server.py to {remote_dir}")
        encoded_script = base64.b64encode(_NODE_SCRIPT.encode()).decode()
        await self._ssh_exec(
            f"echo {encoded_script} | base64 -d > {remote_dir}/node_server.py"
        )
        logger.info(f"Script uploaded successfully")

        # Create config file
        config = {
            "port": self.config.remote_port,
            "tmux": True,  # Enable tmux for session persistence
        }
        if self.config.auth_token:
            config["token"] = self.config.auth_token

        import json
        config_json = json.dumps(config, indent=2)
        encoded_config = base64.b64encode(config_json.encode()).decode()

        logger.info(f"Uploading config.json to {remote_dir}")
        logger.info(f"Config: port={config['port']}, tmux={config['tmux']}, token={'***' if config.get('token') else 'none'}")
        await self._ssh_exec(
            f"echo {encoded_config} | base64 -d > {remote_dir}/config.json"
        )'''

new_deploy = '''        # Upload script via stdin (avoids command line length limits)
        logger.info(f"Uploading node_server.py to {remote_dir}")
        await self._ssh_upload(_NODE_SCRIPT, f"{remote_dir}/node_server.py")
        logger.info(f"Script uploaded successfully")

        # Create config file
        config = {
            "port": self.config.remote_port,
            "tmux": True,  # Enable tmux for session persistence
        }
        if self.config.auth_token:
            config["token"] = self.config.auth_token

        import json
        config_json = json.dumps(config, indent=2)
        logger.info(f"Uploading config.json to {remote_dir}")
        logger.info(f"Config: port={config['port']}, tmux={config['tmux']}, token={'***' if config.get('token') else 'none'}")

        await self._ssh_upload(config_json, f"{remote_dir}/config.json")'''

content = content.replace(old_deploy, new_deploy)

# Write the file back
with open('nanobot/nodes/connection.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("OK - connection.py has been fixed")
