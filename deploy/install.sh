#!/bin/bash
# Installs kiosk mode on the Raspberry Pi: lightdm autologin into a bare openbox session, app service
# (autostart + restart on crash), x11vnc on the physical display (port 5900). Run as: sudo deploy/install.sh
set -e
cd "$(dirname "$0")"
USER_HOME=/home/pi_admin

# 1. Kiosk session (Xorg + openbox) instead of the full desktop
cp -n /etc/lightdm/lightdm.conf /etc/lightdm/lightdm.conf.bak-claude || true
sed -i 's/^autologin-session=.*/autologin-session=openbox/; s/^user-session=.*/user-session=openbox/' /etc/lightdm/lightdm.conf
install -d -o pi_admin -g pi_admin $USER_HOME/.config/openbox
install -m 644 -o pi_admin -g pi_admin openbox/rc.xml $USER_HOME/.config/openbox/rc.xml
install -m 755 -o pi_admin -g pi_admin openbox/autostart $USER_HOME/.config/openbox/autostart

install -d /etc/X11/xorg.conf.d
install -m 644 xorg-kiosk.conf /etc/X11/xorg.conf.d/10-kiosk.conf

# 2. App service
install -m 644 lab-triangulacja.service /etc/systemd/system/lab-triangulacja.service
systemctl daemon-reload
systemctl enable lab-triangulacja.service x11vnc.service
echo "Installed. Reboot (or: systemctl restart lightdm) to enter kiosk mode."
