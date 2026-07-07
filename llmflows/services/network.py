"""Docker network isolation for runner containers.

Creates a custom Docker network that allows internet access but blocks
private/local IP ranges. Configurable allowed_hosts for exceptions.
"""

import logging
import os
import subprocess
from typing import Optional

from ..config import load_system_config

logger = logging.getLogger("llmflows.network")

NETWORK_NAME = os.environ.get("LLMFLOWS_DOCKER_NETWORK", "llmflows-runners")

BLOCKED_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "127.0.0.0/8",
]


def ensure_network() -> str:
    """Create the llmflows-runners Docker network if it doesn't exist.

    Returns the network name.
    """
    result = subprocess.run(
        ["docker", "network", "inspect", NETWORK_NAME],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return NETWORK_NAME

    logger.info("Creating Docker network '%s'", NETWORK_NAME)
    subprocess.run(
        ["docker", "network", "create", "--driver", "bridge", NETWORK_NAME],
        capture_output=True, text=True, check=True,
    )
    _apply_iptables_rules()
    return NETWORK_NAME


def _apply_iptables_rules() -> None:
    """Apply iptables rules to block private IPs on the runner network.

    This requires the orchestrator container to have NET_ADMIN capability
    or for these rules to be applied on the host.
    """
    config = load_system_config()
    allowed_hosts = config.get("network", {}).get("allowed_hosts", [])

    for cidr in BLOCKED_CIDRS:
        cmd = [
            "iptables", "-I", "DOCKER-USER",
            "-s", NETWORK_NAME,
            "-d", cidr,
            "-j", "DROP",
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.debug("Could not apply iptables rule for %s (may need host-level setup)", cidr)

    for host_entry in allowed_hosts:
        host = host_entry.split(":")[0] if ":" in host_entry else host_entry
        cmd = [
            "iptables", "-I", "DOCKER-USER",
            "-s", NETWORK_NAME,
            "-d", host,
            "-j", "ACCEPT",
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.debug("Could not apply iptables ACCEPT rule for %s", host)


def get_network_args(needs_browser_host: bool = False) -> list[str]:
    """Return docker run args for network configuration.

    Args:
        needs_browser_host: If True, adds host access for CDP port 9222.
    """
    network = ensure_network()
    args = ["--network", network]

    if needs_browser_host:
        args.extend(["--add-host", "host.docker.internal:host-gateway"])

    return args


def cleanup_network() -> None:
    """Remove the runner network (e.g. on orchestrator shutdown)."""
    try:
        subprocess.run(
            ["docker", "network", "rm", NETWORK_NAME],
            capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
