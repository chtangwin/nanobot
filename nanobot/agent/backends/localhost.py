"""Utilities for detecting if a host refers to the local machine."""

import socket


def is_localhost(ssh_host: str | None) -> bool:
    """Check if the given ssh_host refers to the local machine.

    Detects the following as local:
        - localhost
        - user@localhost
        - 127.0.0.1 / root@127.0.0.1
        - ::1, 0.0.0.0, 127.x.x.x
        - Actual local IPs (e.g., 10.0.0.72)
        - Local machine hostname (e.g., SP6)

    Args:
        ssh_host: Host string in format "user@host" or just "host"

    Returns:
        True if the host refers to the local machine, False otherwise.
    """
    if not ssh_host:
        return False

    # Extract hostname from "user@host" format
    if "@" in ssh_host:
        hostname = ssh_host.split("@", 1)[1]
    else:
        hostname = ssh_host

    # Strip port if present (host:port)
    if ":" in hostname:
        hostname = hostname.split(":", 1)[0]

    hostname = hostname.strip().lower()

    # Local host indicators
    if hostname in ("localhost", "", "::1"):
        return True

    # IPv4 loopback
    if hostname.startswith("127.") or hostname == "0.0.0.0":
        return True

    # Get local IPs and compare
    local_ips = _get_local_ips()
    if hostname in local_ips:
        return True

    # Check hostname resolution
    try:
        local_hostname = socket.gethostname()
        local_fqdn = socket.getfqdn()

        if hostname in (local_hostname.lower(), local_fqdn.lower()):
            return True

        # Try to resolve the hostname
        try:
            resolved_ip = socket.gethostbyname(hostname)
            if resolved_ip in local_ips:
                return True
        except socket.gaierror:
            pass
    except Exception:
        pass

    return False


def _get_local_ips() -> set[str]:
    """Get all IPv4 addresses assigned to local interfaces."""
    local_ips = set()

    try:
        # Get local IP by connecting to external address
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            local_ips.add(local_ip)
    except Exception:
        pass

    # Always add loopback
    local_ips.add("127.0.0.1")

    return local_ips
