#!/bin/bash
# Installs the autostart/auto-restart service on the Raspberry Pi. Run as: sudo deploy/install.sh
set -e
cd "$(dirname "$0")"
install -m 644 lab-triangulacja.service /etc/systemd/system/lab-triangulacja.service
systemctl daemon-reload
systemctl enable --now lab-triangulacja.service
systemctl --no-pager status lab-triangulacja.service | head -5
