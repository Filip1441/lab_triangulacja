#!/bin/bash
# Disables SSH password login (key only). Refuses to run if no authorized key exists, so you cannot lock yourself out.
# Run as: sudo deploy/ssh-key-only.sh      Undo: sudo rm /etc/ssh/sshd_config.d/10-lab-keyonly.conf && sudo systemctl reload ssh
set -e
KEYS=/home/pi_admin/.ssh/authorized_keys
if [ ! -s "$KEYS" ]; then
    echo "No authorized key in $KEYS - add one first (ssh-copy-id), aborting." >&2
    exit 1
fi
cat > /etc/ssh/sshd_config.d/10-lab-keyonly.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
sshd -t
systemctl reload ssh
echo "SSH password login disabled (key only)."
