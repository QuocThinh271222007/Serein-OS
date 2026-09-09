#!/usr/bin/env bash
# Real, read-only structural inspection of the installed target disk
# image (S7.1 Section 45). Never touches a physical device - the loop
# device here only ever backs a RAW file converted from a qcow2 this
# workflow itself created.
#
# S7.1R6 Objective C: this script previously used `qemu-nbd` + a real
# kernel `/dev/nbd2` device node - the EXACT same class of mechanism
# real Run #5 (RUN_ID=34255177947) proved fails in this CI environment
# for a structurally identical sibling script
# (installer/scripts/hash-disk-image.sh, formerly hash-protected-disk.sh
# on /dev/nbd3). This script's own nbd2 usage had never actually
# executed successfully in any real run either (every prior run timed
# out before "Inspect target disk layout" could run at all - gated on
# a successful install). Rather than risk discovering the identical
# defect class on THIS step - the very next one Run #7 is newly likely
# to reach, now that the real install budget is large enough for
# curtin to actually finish - this is proactively rewritten to use the
# same, already-proven `qemu-img convert` + `losetup -P` approach:
# pure userspace conversion (no root, no kernel module) for the
# temporary raw copy, then the kernel's always-built-in loop driver
# (never a separately loadable module like nbd) for partition access
# on that disposable copy - never the original target image.
#
# This pass also fixes a real, independently-found gap: the ext4 root
# mount below previously used plain `-o ro` (no `noload`) - a
# read-only mount of a filesystem with a dirty journal (plausible for
# a disk a real install/shutdown just touched) can still trigger a
# journal replay even under `-o ro` unless `noload` is also given.
# Fixed here, matching the discipline hash-disk-image.sh's own ext4
# data-partition check already established.
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

for cmd in qemu-img losetup blkid; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "::error::${cmd} is required to inspect the target disk layout" >&2
        exit 1
    fi
done

if [ ! -f "${TARGET_IMG}" ]; then
    echo "::error::${TARGET_IMG} does not exist - cannot inspect a target disk that was never created" >&2
    exit 1
fi

RAW_TMP="$(mktemp -u "$(dirname "${TARGET_IMG}")/.inspect-target-layout-raw.XXXXXX")"
LOOP_DEV=""
_cleanup() {
    if [ -n "${LOOP_DEV}" ]; then
        sudo losetup -d "${LOOP_DEV}" >/dev/null 2>&1 || true
    fi
    rm -f "${RAW_TMP}"
}
trap _cleanup EXIT

echo "==> Converting ${TARGET_IMG} to a temporary raw image for read-only layout inspection (no nbd, no root needed for this step)" >&2
qemu-img convert -f qcow2 -O raw "${TARGET_IMG}" "${RAW_TMP}"

LOOP_DEV="$(sudo losetup --show -f -P -r "${RAW_TMP}")"
sleep 1
sudo partprobe "${LOOP_DEV}" 2>/dev/null || true
sleep 1

ESP_PRESENT="false"
ROOT_PRESENT="false"

if [ -b "${LOOP_DEV}p1" ]; then
    P1_TYPE="$(sudo blkid -o value -s TYPE "${LOOP_DEV}p1" 2>/dev/null || echo "")"
    if [ "${P1_TYPE}" = "vfat" ]; then
        ESP_PRESENT="true"
    fi
fi
SEREIN_CORE_PRESENT="false"
FIRSTBOOT_PROVISIONING="unknown"

if [ -b "${LOOP_DEV}p2" ]; then
    P2_TYPE="$(sudo blkid -o value -s TYPE "${LOOP_DEV}p2" 2>/dev/null || echo "")"
    if [ "${P2_TYPE}" = "ext4" ]; then
        ROOT_PRESENT="true"

        # Section 27, 48: prove the real /etc/serein/install-state.json
        # handoff marker exists on the installed root - read-only mount
        # of the loop-backed COPY, never written to, never even the
        # original image. `noload`: never replay a dirty ext4 journal,
        # even under a read-only mount.
        MNT_ROOT="$(mktemp -d)"
        if sudo mount -o ro,noload "${LOOP_DEV}p2" "${MNT_ROOT}" 2>/dev/null; then
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

echo "target_esp_present=${ESP_PRESENT}"
echo "target_root_present=${ROOT_PRESENT}"
echo "serein_core_present=${SEREIN_CORE_PRESENT}"
echo "firstboot_provisioning=${FIRSTBOOT_PROVISIONING}"
