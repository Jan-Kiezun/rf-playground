#!/usr/bin/env bash
# setup-host.sh — one-time HOST configuration for RTL-SDR
#
# Run this script on the HOST machine (not inside Docker) before starting the
# stack for the first time, or after a kernel upgrade, or any time you see:
#   "PLL not locked" in rtl_fm output, or
#   "usb_claim_interface error -6" in rtl_tcp/rtl_fm output.
#
# What it does:
#   1. Blacklists the kernel DVB-T module that competes with librtlsdr for the
#      USB dongle.  Without this the kernel driver grabs the device first,
#      rtl_fm can't properly initialise the tuner, and you get static or silence.
#   2. Unloads the conflicting module from the running kernel (takes effect
#      immediately without a reboot).
#   3. Installs udev rules so the dongle is accessible to members of "plugdev"
#      without requiring root, which is what the Docker container relies on when
#      /dev/bus/usb is mapped in.
#
# Reference: https://www.rtl-sdr.com/rtl-sdr-quick-start-guide/
#
# Usage:
#   chmod +x setup-host.sh
#   sudo ./setup-host.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Blacklist conflicting kernel modules ───────────────────────────────────
BLACKLIST_FILE="/etc/modprobe.d/rtlsdr-blacklist.conf"
echo "==> Writing module blacklist to ${BLACKLIST_FILE}"
cat > "${BLACKLIST_FILE}" << 'EOF'
# Prevent the generic DVB-T driver from grabbing RTL2832U dongles before
# librtlsdr can claim them.  Required for rtl_fm / rtl_tcp to work correctly.
blacklist dvb_usb_rtl28xxu
blacklist dvb_usb_v2
blacklist rtl2832
blacklist rtl2830
blacklist dvb_core
EOF
echo "    Done."

# ── 2. Unload the module if it is currently loaded ───────────────────────────
echo "==> Attempting to unload dvb_usb_rtl28xxu from the running kernel..."
if lsmod | grep -q dvb_usb_rtl28xxu; then
    modprobe -r dvb_usb_rtl28xxu && echo "    Module unloaded." || \
        echo "    WARNING: could not unload — unplug and re-plug the dongle, or reboot."
else
    echo "    Module not loaded — nothing to unload."
fi

# ── 3. Install udev rules ─────────────────────────────────────────────────────
RULES_SRC="${SCRIPT_DIR}/rtl-sdr.rules"
RULES_DST="/etc/udev/rules.d/rtl-sdr.rules"
if [[ -f "${RULES_SRC}" ]]; then
    echo "==> Installing udev rules to ${RULES_DST}"
    cp "${RULES_SRC}" "${RULES_DST}"
    udevadm control --reload-rules
    udevadm trigger
    echo "    Done."
else
    echo "    WARNING: ${RULES_SRC} not found — skipping udev rules installation."
fi

# ── 4. Ensure the current user is in the plugdev group ───────────────────────
SUDO_USER="${SUDO_USER:-}"
if [[ -n "${SUDO_USER}" ]] && ! groups "${SUDO_USER}" | grep -q plugdev; then
    echo "==> Adding ${SUDO_USER} to the plugdev group"
    usermod -aG plugdev "${SUDO_USER}"
    echo "    Done. Log out and back in for the group membership to take effect."
fi

echo ""
echo "==> Host setup complete."
echo "    If the dongle was plugged in during this run, unplug and re-plug it now."
echo "    Then restart the Docker stack:  docker compose down && docker compose up -d"
