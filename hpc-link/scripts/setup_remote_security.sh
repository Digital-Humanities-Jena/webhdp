#!/bin/bash
# Helper script to deploy security wrapper to HPC
# Usage: ./scripts/setup_remote_security.sh <host> <user> [identity_file]

HOST="${1:-hpc-login.example.edu}"
USER="${2:-webhdp-user}"
KEY="${3:-secrets/ssh_key}"

echo "Deploying HPC Link Security Wrapper to $USER@$HOST..."

# 1. Upload Wrapper
scp -i "$KEY" scripts/hpc-link-wrapper.sh "$USER@$HOST:~/hpc-link-wrapper.sh"
if [ $? -ne 0 ]; then
    echo "Error: Failed to upload wrapper script."
    exit 1
fi

# 2. Make Executable
ssh -i "$KEY" "$USER@$HOST" "chmod +x ~/hpc-link-wrapper.sh"

echo "Wrapper uploaded."
echo "CRITICAL: You must manually update authorized_keys on $HOST to use this wrapper."
echo "Example line:"
echo 'command="~/hpc-link-wrapper.sh" ssh-ed25519 ... key-content ...'
