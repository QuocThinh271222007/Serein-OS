#!/usr/bin/env bash
# Real, read-only structural inspection of the installed target disk
# image (S7.1 Section 45) - connects it via qemu-nbd (never mounts
# read-write), checks the real partition table/filesystem types, and
# disconnects. Never touches a physical device - the nbd device here
# only ever backs a qcow2 FILE this workflow itself created.
#
# Usage: ./installer/scripts/inspect-target-layout.sh <target-disk-qcow2>
#
# Prints, to stdout, lines suitable for `>> "$GITHUB_OUTPUT"`:
#   target_esp_present=true|false
#   target_root_present=true|false
#   serein_core_present=true|false
#   firstboot_provisioning=pending|complete|unknown

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <target-disk-qcow2>" >&2
    exit 1
fi
TARGET_IMG="$1"

for cmd in qemu-nbd blkid partprobe; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "::error::${cmd} is required to inspect the target disk layout" >&2
        exit 1
    fi
done

sudo modprobe nbd max_part=8
NBD_DEV="/dev/nbd2"

sudo qemu-nbd --connect="${NBD_DEV}" --read-only "${TARGET_IMG}"
trap 'sudo qemu-nbd --disconnect "${NBD_DEV}" >/dev/null 2>&1 || true' EXIT
sleep 1
sudo partprobe "${NBD_DEV}" || true
sleep 1

ESP_PRESENT="false"
ROOT_PRESENT="false"

if [ -b "${NBD_DEV}p1" ]; then
    P1_TYPE="$(sudo blkid -o value -s TYPE "${NBD_DEV}p1" 2>/dev/null || echo "")"
    if [ "${P1_TYPE}" = "vfat" ]; then
        ESP_PRESENT="true"
    fi
fi
SEREIN_CORE_PRESENT="false"
FIRSTBOOT_PROVISIONING="unknown"

if [ -b "${NBD_DEV}p2" ]; then
    P2_TYPE="$(sudo blkid -o value -s TYPE "${NBD_DEV}p2" 2>/dev/null || echo "")"
    if [ "${P2_TYPE}" = "ext4" ]; then
        ROOT_PRESENT="true"

        # Section 27, 48: prove the real /etc/serein/install-state.json
        # handoff marker exists on the installed root - read-only mount,
        # never written to.
        MNT_ROOT="$(mktemp -d)"
        if sudo mount -o ro "${NBD_DEV}p2" "${MNT_ROOT}" 2>/dev/null; then
            STATE_FILE="${MNT_ROOT}/etc/serein/install-state.json"
            if [ -f "${STATE_FILE}" ]; then
                SEREIN_CORE_PRESENT="true"
                FIRSTBOOT_PROVISIONING="$(
                    sudo python3 -c \
                        "import json;print(json.load(open('${STATE_FILE}'))['firstboot_provisioning'])" \
                        2>/dev/null || echo "unknown"
                )"
            fi
            sudo umount "${MNT_ROOT}"
        fi
        rmdir "${MNT_ROOT}"
    fi
fi

sudo qemu-nbd --disconnect "${NBD_DEV}"
trap - EXIT

echo "target_esp_present=${ESP_PRESENT}"
echo "target_root_present=${ROOT_PRESENT}"
echo "serein_core_present=${SEREIN_CORE_PRESENT}"
echo "firstboot_provisioning=${FIRSTBOOT_PROVISIONING}"
