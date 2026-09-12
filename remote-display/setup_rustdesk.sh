#!/bin/bash
# ---------------------------------------------------------------------------
# UNO Q remote-display setup: RustDesk + (optional) dummy Xorg driver.
#
# Run this ON THE BOARD, over SSH:
#   ssh arduino@<board-ip>
#   scp -r remote-display arduino@<board-ip>:~/
#   ssh arduino@<board-ip> "chmod +x ~/remote-display/setup_rustdesk.sh && ~/remote-display/setup_rustdesk.sh"
#
# Safe to re-run; steps that are already done are skipped/idempotent
# where practical. Read it before running if you're the "trust but
# verify" type -- it edits system config (Xorg, lightdm) with sudo.
# ---------------------------------------------------------------------------
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUSTDESK_VERSION="1.4.7"
RUSTDESK_DEB="rustdesk-${RUSTDESK_VERSION}-aarch64.deb"
RUSTDESK_URL="https://github.com/rustdesk/rustdesk/releases/download/${RUSTDESK_VERSION}/${RUSTDESK_DEB}"

echo "== 1/5: Installing RustDesk =="
if ! command -v rustdesk >/dev/null 2>&1; then
    cd /tmp
    wget -q --show-progress "$RUSTDESK_URL" -O "$RUSTDESK_DEB" || {
        echo "Download failed. Check https://github.com/rustdesk/rustdesk/releases for the current version"
        echo "and edit RUSTDESK_VERSION at the top of this script."
        exit 1
    }
    sudo apt install -y "./$RUSTDESK_DEB"
else
    echo "RustDesk already installed, skipping."
fi

echo
echo "== 2/5: Do you have a real HDMI/DisplayPort monitor reliably attached? =="
read -rp "Type 'y' if yes (skip dummy driver), or 'n' to install a virtual display [y/n]: " HAS_DISPLAY
if [[ "$HAS_DISPLAY" =~ ^[Nn]$ ]]; then
    echo "Installing dummy Xorg driver..."
    sudo apt install -y xserver-xorg-video-dummy
    sudo mkdir -p /etc/X11/xorg.conf.d
    sudo cp "$SCRIPT_DIR/10-dummy.conf" /etc/X11/xorg.conf.d/10-dummy.conf
    echo "Restarting lightdm to pick up the new display..."
    sudo systemctl reset-failed lightdm || true
    sudo systemctl restart lightdm
    sleep 3
    echo "Checking for an enumerable display..."
    sudo XAUTHORITY=/var/run/lightdm/root/:0 DISPLAY=:0 xrandr --query || \
        echo "WARNING: xrandr didn't report a display -- double check /etc/X11/xorg.conf.d/10-dummy.conf"
else
    echo "Skipping dummy driver -- using your existing real display."
fi

echo
echo "== 3/5: Autostart RustDesk in the desktop session =="
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/rustdesk.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=RustDesk
Exec=/usr/bin/rustdesk
X-GNOME-Autostart-enabled=true
EOF
echo "Added ~/.config/autostart/rustdesk.desktop"

echo
echo "== 4/5: Enable lightdm autologin (so the board reaches a desktop unattended) =="
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf > /dev/null << EOF
[Seat:*]
autologin-user=$(whoami)
autologin-user-timeout=0
EOF

echo
echo "== 5/5: Disable the idle screen lock (no point locking a headless board) =="
mkdir -p ~/.config/autostart
if [ -f /etc/xdg/autostart/light-locker.desktop ]; then
    cp /etc/xdg/autostart/light-locker.desktop ~/.config/autostart/light-locker.desktop
    if ! grep -q "^Hidden=true" ~/.config/autostart/light-locker.desktop; then
        echo "Hidden=true" >> ~/.config/autostart/light-locker.desktop
    fi
    echo "light-locker autostart disabled for this user."
else
    echo "light-locker.desktop not found, skipping (may not be installed)."
fi

cat << 'EOF'

---------------------------------------------------------------
Setup done. Next steps:

1. Reboot the board:  sudo reboot
2. After ~30-60s, open the RustDesk client on your PC/Mac
   (download: https://rustdesk.com/) and the board should
   appear in your peer list automatically (same network).
3. First connection: on the BOARD run  `DISPLAY=:0 rustdesk &`
   once, then Settings -> Security -> set a permanent password
   so you don't have to re-enter a one-time code every time.
4. Connect from your PC, open a terminal in the remote session,
   and launch the game:
       cd ~/ARDU-cade/python && python3 main.py
---------------------------------------------------------------
EOF
