#!/bin/bash
# RTL-SDR Connection & Signal Test Script
# Tests USB detection, driver setup, and signal reception

set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─── Config ───────────────────────────────────────────────────────────────────
FREQ_MHZ="100.3"      # FM radio frequency in MHz (change to a strong local station)
SAMPLE_RATE="2400000" # 2.4 MSPS
GAIN="40"             # Tuner gain (dB); use "0" for auto
CAPTURE_SECONDS=5     # How long to capture samples
TEST_FILE="/tmp/rtlsdr_test_capture.bin"

# ─── Helpers ──────────────────────────────────────────────────────────────────
pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
section() {
    echo -e "\n${BLUE}══════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}══════════════════════════════════════════${NC}"
}

PASS_COUNT=0
FAIL_COUNT=0

check() {
    if "$@"; then
        ((PASS_COUNT++)) || true
        return 0
    else
        ((FAIL_COUNT++)) || true
        return 1
    fi
}

# ─── 1. Check required tools ──────────────────────────────────────────────────
section "1. Checking required tools"

REQUIRED_TOOLS=("lsusb" "rtl_test" "rtl_sdr")
MISSING=()

for tool in "${REQUIRED_TOOLS[@]}"; do
    if command -v "$tool" &>/dev/null; then
        pass "$tool is installed ($(command -v "$tool"))"
        ((PASS_COUNT++)) || true
    else
        fail "$tool not found"
        MISSING+=("$tool")
        ((FAIL_COUNT++)) || true
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    warn "Missing tools detected. Install them with:"
    warn "  sudo apt install usbutils rtl-sdr     # Debian/Ubuntu"
    warn "  sudo dnf install usbutils rtl-sdr     # Fedora/RHEL"
    warn "  sudo pacman -S usbutils rtl-sdr       # Arch Linux"
    if [[ " ${MISSING[*]} " =~ " rtl_test " ]] || [[ " ${MISSING[*]} " =~ " rtl_sdr " ]]; then
        echo -e "\n${RED}Cannot continue without rtl-sdr tools. Exiting.${NC}"
        exit 1
    fi
fi

# ─── 2. USB device detection ─────────────────────────────────���────────────────
section "2. Detecting RTL-SDR USB device"

# Known RTL-SDR USB vendor:product IDs
RTL_IDS=(
    "0bda:2832" # Realtek RTL2832U
    "0bda:2838" # Realtek RTL2838
    "0bda:2831" # Realtek RTL2831U
    "1d50:604b" # Osmocom RTL-SDR
    "0458:707f" # Generic RTL2832U
)

FOUND_DEVICE=""
for id in "${RTL_IDS[@]}"; do
    if lsusb | grep -qi "${id}"; then
        FOUND_DEVICE="$id"
        break
    fi
done

if [[ -n "$FOUND_DEVICE" ]]; then
    DEVICE_INFO=$(lsusb | grep -i "$FOUND_DEVICE")
    pass "RTL-SDR device found: $DEVICE_INFO"
    ((PASS_COUNT++)) || true
else
    # Try generic Realtek detection
    if lsusb | grep -qi "realtek"; then
        warn "Realtek USB device found but ID not in known RTL-SDR list:"
        lsusb | grep -i "realtek"
        warn "It might still work — continuing."
        ((PASS_COUNT++)) || true
    else
        fail "No RTL-SDR USB device detected. Is it plugged in?"
        ((FAIL_COUNT++)) || true
        info "Run 'lsusb' to list all USB devices."
    fi
fi

# ─── 3. Check udev rules / permissions ───────────────────────────────────────
section "3. Checking udev rules and USB permissions"

UDEV_FILE=""
for f in /etc/udev/rules.d/rtl-sdr.rules /lib/udev/rules.d/60-rtl-sdr.rules /usr/lib/udev/rules.d/60-rtl-sdr.rules; do
    if [[ -f "$f" ]]; then
        UDEV_FILE="$f"
        break
    fi
done

if [[ -n "$UDEV_FILE" ]]; then
    pass "udev rules found: $UDEV_FILE"
    ((PASS_COUNT++)) || true
else
    warn "No RTL-SDR udev rules found. You may need to run as root, or install rules:"
    warn "  sudo tee /etc/udev/rules.d/rtl-sdr.rules <<EOF"
    warn "  SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"0bda\", ATTRS{idProduct}==\"2832\", MODE=\"0666\""
    warn "  SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"0bda\", ATTRS{idProduct}==\"2838\", MODE=\"0666\""
    warn "  EOF"
    warn "  sudo udevadm control --reload && sudo udevadm trigger"
    ((FAIL_COUNT++)) || true
fi

# ─── 4. Check that dvb_usb_rtl28xxu is blacklisted ───────────────────────────
section "4. Checking kernel driver conflicts"

CONFLICT_MOD="dvb_usb_rtl28xxu"
if lsmod | grep -q "$CONFLICT_MOD"; then
    fail "Kernel module '$CONFLICT_MOD' is loaded and will block rtl-sdr!"
    warn "Fix with:"
    warn "  sudo rmmod $CONFLICT_MOD"
    warn "  echo 'blacklist $CONFLICT_MOD' | sudo tee /etc/modprobe.d/rtlsdr-blacklist.conf"
    warn "  sudo modprobe -r $CONFLICT_MOD"
    ((FAIL_COUNT++)) || true
else
    pass "No conflicting kernel module ($CONFLICT_MOD) loaded"
    ((PASS_COUNT++)) || true
fi

# Also check blacklist files
if grep -rq "$CONFLICT_MOD" /etc/modprobe.d/ 2>/dev/null; then
    pass "$CONFLICT_MOD is blacklisted in modprobe.d"
    ((PASS_COUNT++)) || true
else
    warn "$CONFLICT_MOD is NOT blacklisted — it may load on reboot/re-plug"
    warn "  echo 'blacklist $CONFLICT_MOD' | sudo tee /etc/modprobe.d/rtlsdr-blacklist.conf"
fi

# ─── 5. rtl_test device enumeration ──────────────────────────────────────────
section "5. Running rtl_test device enumeration"

info "Running: rtl_test -t (enumerate & test device, 5s timeout)"
if timeout 10 rtl_test -t 2>&1 | tee /tmp/rtl_test_output.txt; then
    pass "rtl_test completed successfully"
    ((PASS_COUNT++)) || true
else
    EXIT=$?
    if [[ $EXIT -eq 124 ]]; then
        fail "rtl_test timed out — device may be unresponsive"
    else
        fail "rtl_test failed (exit code $EXIT)"
        info "Output saved to /tmp/rtl_test_output.txt"
        cat /tmp/rtl_test_output.txt
    fi
    ((FAIL_COUNT++)) || true
fi

# ─── 6. Capture a short IQ sample ────────────────────────────────────────────
section "6. Capturing IQ samples at ${FREQ_MHZ} MHz"

FREQ_HZ=$(echo "$FREQ_MHZ * 1000000" | bc | cut -d. -f1)
info "Frequency : ${FREQ_MHZ} MHz (${FREQ_HZ} Hz)"
info "Sample rate: ${SAMPLE_RATE} sps"
info "Gain      : ${GAIN} dB"
info "Duration  : ${CAPTURE_SECONDS} seconds"
info "Output    : ${TEST_FILE}"

rm -f "$TEST_FILE"

if timeout $((CAPTURE_SECONDS + 5)) rtl_sdr \
    -f "$FREQ_HZ" \
    -s "$SAMPLE_RATE" \
    -g "$GAIN" \
    -n $((SAMPLE_RATE * CAPTURE_SECONDS)) \
    "$TEST_FILE" 2>&1; then

    if [[ -f "$TEST_FILE" ]]; then
        FILE_SIZE=$(stat -c%s "$TEST_FILE")
        EXPECTED_SIZE=$((SAMPLE_RATE * CAPTURE_SECONDS * 2)) # 2 bytes per IQ sample
        pass "Capture file created: ${TEST_FILE} (${FILE_SIZE} bytes)"

        if [[ $FILE_SIZE -gt $((EXPECTED_SIZE / 2)) ]]; then
            pass "File size looks reasonable (expected ~${EXPECTED_SIZE} bytes)"
            ((PASS_COUNT++)) || true
        else
            warn "File is smaller than expected (${FILE_SIZE} < ${EXPECTED_SIZE}) — possible dropped samples"
            ((FAIL_COUNT++)) || true
        fi

        # Check for non-zero data (all-zeros = no signal / DC bias issue)
        if command -v xxd &>/dev/null; then
            NONZERO=$(xxd "$TEST_FILE" | head -50 | grep -v "0000 0000 0000 0000" | wc -l)
            if [[ $NONZERO -gt 5 ]]; then
                pass "Captured data appears non-trivial (signal present)"
                ((PASS_COUNT++)) || true
            else
                warn "Captured data looks like zeros — possible no signal or antenna issue"
            fi
        fi

        ((PASS_COUNT++)) || true
    else
        fail "No capture file created"
        ((FAIL_COUNT++)) || true
    fi
else
    fail "rtl_sdr capture failed"
    ((FAIL_COUNT++)) || true
fi

# ─── 7. Summary ───────────────────────────────────────────────────────────────
section "Summary"

TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo -e "Tests run : ${TOTAL}"
echo -e "${GREEN}Passed    : ${PASS_COUNT}${NC}"
echo -e "${RED}Failed    : ${FAIL_COUNT}${NC}"

if [[ $FAIL_COUNT -eq 0 ]]; then
    echo -e "\n${GREEN}✔ All checks passed! Your RTL-SDR is working.${NC}"
    exit 0
else
    echo -e "\n${YELLOW}⚠ Some checks failed. Review the output above for fix instructions.${NC}"
    exit 1
fi
