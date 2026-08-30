"""SSRF protection guardrail validating URLs against private, loopback, and metadata IPs."""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
}


def is_safe_url(url: str) -> Tuple[bool, str]:
    """
    Validate that a URL uses safe protocols (http/https) and does not point
    to local, loopback, private, carrier-grade NAT, or cloud metadata IPs.
    """
    if not url or not isinstance(url, str):
        return False, "Empty or invalid URL"

    try:
        parsed = urlparse(url.strip())
    except Exception as e:
        return False, f"URL parse error: {str(e)}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Invalid scheme: '{parsed.scheme}'. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL."

    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        return False, f"Access to blocked host '{hostname}' is denied."

    # Resolve IP addresses for hostname
    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return False, f"Could not resolve hostname '{hostname}'"

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid resolved IP '{ip_str}'"

        if ip_obj.is_private:
            return False, f"Access to private IP range ({ip_str}) is prohibited."
        if ip_obj.is_loopback:
            return False, f"Access to loopback address ({ip_str}) is prohibited."
        if ip_obj.is_link_local:
            return False, f"Access to link-local/cloud-metadata IP ({ip_str}) is prohibited."
        if ip_obj.is_multicast:
            return False, f"Access to multicast IP ({ip_str}) is prohibited."
        if ip_obj.is_reserved:
            return False, f"Access to reserved IP ({ip_str}) is prohibited."

    return True, "URL is safe"
