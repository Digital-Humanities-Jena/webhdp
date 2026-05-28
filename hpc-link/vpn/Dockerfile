FROM debian:bookworm-slim

# Install OpenConnect and networking tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    openconnect \
    iptables \
    iproute2 \
    curl \
    ca-certificates \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Create entrypoint script
COPY vpn-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
