#!/bin/bash
# HPC Link Security Wrapper
# Restricts SSH commands to specific allowed binaries and paths.
# Deploy to: ~/hpc-link-wrapper.sh
# Usage in authorized_keys: command="~/hpc-link-wrapper.sh" ssh-ed25519 ...

# Configuration
ALLOWED_CMDS=("sbatch" "squeue" "scancel" "scontrol" "srun" "nvidia-smi" "sinfo" "uv" "mkdir" "rm" "mv" "ls" "stat")
# Note: Filesystem operations via 'internal-sftp' are handled separately below.
# Simple commands like 'ls' or 'mkdir' might be sent via SSH exec (ssh_manager.run_command).
# We must allow them if the app uses them via SSH exec.
# App uses SFTP for most file ops, but might use exec for some?
# - sbatch, squeue, etc are via exec.
# - mkdir: app/routers/files.py uses sftp.makedirs (SFTP)
# - rm: sftp.remove (SFTP)
# - stat: sftp.stat (SFTP)
# So 'ls', 'mkdir', 'rm' might NOT be needed in ALLOWED_CMDS if purely SFTP used.
# But 'sbatch' needs to read the script.
# 'uv' is used for execution.

# Verify usage:
# App uses: sbatch, squeue, scancel, scontrol, srun, nvidia-smi, sinfo
# And 'tail -f' (via create_process). So 'tail' must be allowed.
ALLOWED_CMDS+=("tail")

# Log attempt (Debugging - disable in production if high volume)
# echo "$(date) $SSH_ORIGINAL_COMMAND" >> ~/hpc-link-wrapper.log

if [[ -z "$SSH_ORIGINAL_COMMAND" ]]; then
    echo "Access denied: Interactive shell not allowed."
    exit 1
fi

# Split command into array
read -ra CMD_PARTS <<< "$SSH_ORIGINAL_COMMAND"
CMD="${CMD_PARTS[0]}"

# 1. SFTP Support
# AsyncSSH requesting SFTP subsystem usually results in SSH_ORIGINAL_COMMAND being empty?
# No, if ForceCommand/command= is used, it captures the subsystem request usually as the command?
# Actually, for subsystem 'sftp', the server normally executes 'sftp-server'.
# If we have a wrapper, we must handle it.
# OpenSSH with 'command=' sets SSH_ORIGINAL_COMMAND to the command line.
# For subsystem, it might be 'sftp-server' or similar depending on client.
# Let's support standard sftp server paths.
SFTP_SERVER="/usr/libexec/openssh/sftp-server"
if [[ ! -x "$SFTP_SERVER" ]]; then
    SFTP_SERVER="/usr/lib/openssh/sftp-server"
fi

if [[ "$CMD" == "$SFTP_SERVER" || "$CMD" == "sftp-server" || "$SSH_ORIGINAL_COMMAND" == "internal-sftp" ]]; then
    exec $SFTP_SERVER
fi

# 2. Check Allowed Commands
ALLOWED=false

# Helper to check if string is in array
for permitted in "${ALLOWED_CMDS[@]}"; do
    if [[ "$CMD" == "$permitted" ]]; then
        ALLOWED=true
        break
    fi
    # Handle absolute paths (e.g. /usr/bin/sbatch)
    if [[ "$CMD" == */"$permitted" ]]; then
        ALLOWED=true
        break
    fi
done

if [[ "$ALLOWED" == "false" ]]; then
    echo "Access denied: Command '$CMD' not allowed by HPC Link Wrapper."
    exit 1
fi

# 3. Execution
# We allow the original command arguments.
# Security Note: This does NOT filter arguments (e.g. 'cat /etc/shadow').
# We rely on:
# a) The allowed commands being generally safe (sbatch, squeue)
# b) The App user (hpc-link) having limited permissions (standard user)
# c) The App logic validating paths before sending commands.
# To be stricter, we would parse arguments here.

exec $SSH_ORIGINAL_COMMAND
