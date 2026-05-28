#!/bin/bash
set -e

VPN_SERVER="${VPN_SERVER:-vpn.example.edu}"
VPN_USER="${VPN_USER:-}"
VPN_PASSWORD_FILE="${VPN_PASSWORD_FILE:-/run/secrets/vpn_password}"

echo "=== HPC Link VPN Gateway ==="
echo "Server: $VPN_SERVER"
echo "User: $VPN_USER"

# Read password from file
if [ -f "$VPN_PASSWORD_FILE" ]; then
    VPN_PASSWORD=$(cat "$VPN_PASSWORD_FILE")
else
    echo "ERROR: Password file not found: $VPN_PASSWORD_FILE"
    exit 1
fi

# Connect to VPN - openconnect handles routing and DNS automatically
connect_vpn() {
    echo "Connecting to VPN..."
    VPN_PASSWORD=$(cat "$VPN_PASSWORD_FILE")

    # Use standard echo pipe which is often more reliable for openconnect stdin
    echo "$VPN_PASSWORD" | openconnect \
        --protocol=anyconnect \
        --user="$VPN_USER" \
        --passwd-on-stdin \
        --no-dtls \
        --useragent="AnyConnect" \
        --disable-ipv6 \
        --background \
        --pid-file=/var/run/openconnect.pid \
        "$VPN_SERVER"

    # Wait for tunnel to come up
    sleep 5

    if ip link show tun0 > /dev/null 2>&1; then
        echo "VPN connected successfully!"
        ip addr show tun0
        echo "--- Route table ---"
        ip route
        echo "--- DNS config ---"
        cat /etc/resolv.conf
        return 0
    else
        echo "ERROR: VPN tunnel not established"
        return 1
    fi
}

# Test connectivity
test_connectivity() {
    echo "Testing DNS resolution..."
    if nslookup hpc-login.example.edu > /dev/null 2>&1; then
        echo "DNS resolution: OK"
    else
        echo "DNS resolution: FAILED (may still work via IP)"
    fi

    echo "Testing SSH port connectivity..."
    if nc -zw5 hpc-login.example.edu 22 2>/dev/null; then
        echo "SSH port: OK"
    else
        echo "SSH port: Not reachable via hostname"
    fi
}

# Health check function - keep container running and monitor
health_check() {
    while true; do
        if ! ip link show tun0 > /dev/null 2>&1; then
            echo "VPN tunnel down, reconnecting..."
            connect_vpn || sleep 10
        fi
        sleep 30
    done
}

# Main
echo "Starting VPN gateway..."
connect_vpn
test_connectivity

echo "VPN ready, starting health check loop..."
# Start health check loop and keep container running
health_check
