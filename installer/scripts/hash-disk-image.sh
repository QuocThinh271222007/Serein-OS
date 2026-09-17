#!/usr/bin/env bash
# Real, read-only measurement of a fixture disk image's container vs.
# guest-visible logical content (S7.1R4 Section 8-9; generalized in
# S7.1R5 to cover both the protected AND target disks - Objective D).
# Separately measures four distinct facts a plain container-level
# `sha256sum <file>` alone cannot distinguish between:
#
#   container_sha256 - sha256 of the raw qcow2 FILE. A qcow2
#     container's bytes can change from the format's own internal
#     bookkeeping (lazy refcounts, dirty-bit state on open/close)
#     purely from being opened for write access, even with zero
#     guest-visible content change - this measurement alone cannot
#     distinguish that from a real write.
#
#   logical_sha256 - sha256 of the FULL guest-visible logical block
#     content - proves whether the bytes a guest OS would actually
#     see changed, independent of qcow2's own container-format
#     metadata.
#
#   esp_sentinel_sha256 / data_sentinel_sha256 - sha256 of the two
#     real sentinel files create-fixture-disks.sh writes
#     (EFI/Microsoft/Boot/sentinel.txt on the FAT32 ESP, SENTINEL.txt
#     on the ext4 data partition) - an additional, filesystem-level
#     integrity marker. On the TARGET disk, `data_sentinel_present`
#     honestly flipping to `false` after a real successful install is
#     itself expected/correct evidence (curtin replaces the original
#     pre-populated partition table with Serein's own layout) - never
#     treated as an error by this script.
#
# S7.1R5 Corrective A: the ORIGINAL S7.1R4 implementation
# (hash-protected-disk.sh) used `qemu-nbd` + a real kernel /dev/nbdX
# device node to expose a qcow2 image's logical content. Real Run #5
# (RUN_ID=34255177947) proved this fails in this exact CI environment
# - the workflow step calling it ("Hash protected disk (pre-install
# baseline)") was the FIRST real workflow failure. The EXACT failing
# primitive could not be proven locally (this development environment
# has no qemu-nbd/nbd kernel module to reproduce against - BLOCKED),
# but nbd device-node access was the one operation in that script with
# no precedent of PROVEN success anywhere else in this repository:
# create-fixture-disks.sh's own nbd0/nbd1 usage IS proven working (every
# real run reaches fixture creation), but nbd2/nbd3 usage
# (inspect-target-layout.sh and the original hash-protected-disk.sh)
# had never actually executed successfully in any real run before
# Run #5's failure.
#
# This implementation removes the nbd/kernel-module/device-node
# dependency for the logical-content measurement entirely:
# `qemu-img convert` is a pure userspace tool (already installed via
# the `qemu-utils` package), requires no root privilege and no kernel
# module, and converting a qcow2 image to a new raw FILE is itself a
# read-only operation on the SOURCE image. For the two sentinel-file
# checks (which do need real partition/filesystem access), a
# `losetup -P` (partition-scanning) read-only loop device on the
# already-CONVERTED raw file is used instead of qemu-nbd on the live
# qcow2 - `losetup` uses the kernel's always-built-in loop driver
# (never a separately loadable module like nbd, and already proven
# available on every GitHub-hosted Ubuntu runner), and it only ever
# operates on the disposable temp file, never the original image.
#
# Usage: ./installer/scripts/hash-disk-image.sh <qcow2-image>
#
# Prints, to stdout, lines suitable for `>> "$GITHUB_OUTPUT"`:
#   container_sha256=<hex>
#   logical_sha256=<hex>
#   esp_sentinel_sha256=<hex-or-empty>
#   esp_sentinel_present=true|false
#   data_sentinel_sha256=<hex-or-empty>
#   data_sentinel_present=true|false

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <qcow2-image>" >&2
    exit 1
fi
IMG="$1"

for cmd in sha256sum qemu-img losetup blkid; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "::error::${cmd} is required to hash the disk image" >&2
        exit 1
    fi
done

if [ ! -f "${IMG}" ]; then
    echo "::error::${IMG} does not exist - cannot hash a disk image that was never created" >&2
    exit 1
fi

CONTAINER_SHA256="$(sha256sum "${IMG}" | cut -d' ' -f1)"

RAW_TMP="$(mktemp -u "$(dirname "${IMG}")/.hash-disk-image-raw.XXXXXX")"
LOOP_DEV=""
_cleanup() {
    if [ -n "${LOOP_DEV}" ]; then
        sudo losetup -d "${LOOP_DEV}" >/dev/null 2>&1 || true
    fi
    rm -f "${RAW_TMP}"
}
trap _cleanup EXIT

echo "==> Converting ${IMG} to a temporary raw image for read-only logical hashing (no nbd, no root needed for this step)" >&2
qemu-img convert -f qcow2 -O raw "${IMG}" "${RAW_TMP}"

LOGICAL_SHA256="$(sha256sum "${RAW_TMP}" | cut -d' ' -f1)"

LOOP_DEV="$(sudo losetup --show -f -P -r "${RAW_TMP}")"
sleep 1
sudo partprobe "${LOOP_DEV}" 2>/dev/null || true
sleep 1

ESP_SENTINEL_SHA256=""
ESP_SENTINEL_PRESENT="false"
if [ -b "${LOOP_DEV}p1" ]; then
    P1_TYPE="$(sudo blkid -o value -s TYPE "${LOOP_DEV}p1" 2>/dev/null || echo "")"
    if [ "${P1_TYPE}" = "vfat" ]; then
        MNT_ESP="$(mktemp -d)"
        if sudo mount -o ro "${LOOP_DEV}p1" "${MNT_ESP}" 2>/dev/null; then
            SENTINEL_FILE="${MNT_ESP}/EFI/Microsoft/Boot/sentinel.txt"
            if [ -f "${SENTINEL_FILE}" ]; then
                ESP_SENTINEL_SHA256="$(sudo sha256sum "${SENTINEL_FILE}" | cut -d' ' -f1)"
                ESP_SENTINEL_PRESENT="true"
            fi
            sudo umount "${MNT_ESP}"
        fi
        rmdir "${MNT_ESP}"
    fi
fi

DATA_SENTINEL_SHA256=""
DATA_SENTINEL_PRESENT="false"
if [ -b "${LOOP_DEV}p2" ]; then
    P2_TYPE="$(sudo blkid -o value -s TYPE "${LOOP_DEV}p2" 2>/dev/null || echo "")"
    if [ "${P2_TYPE}" = "ext4" ]; then
        MNT_DATA="$(mktemp -d)"
        # `noload`: never replay a dirty ext4 journal, even under a
        # read-only mount - guarantees this measurement cannot itself
        # be a mutation vector (it operates on the loop-backed COPY in
        # any case, never the original image, but the discipline is
        # kept consistent regardless).
        if sudo mount -o ro,noload "${LOOP_DEV}p2" "${MNT_DATA}" 2>/dev/null; then
            SENTINEL_FILE="${MNT_DATA}/SENTINEL.txt"
            if [ -f "${SENTINEL_FILE}" ]; then
                DATA_SENTINEL_SHA256="$(sudo sha256sum "${SENTINEL_FILE}" | cut -d' ' -f1)"
                DATA_SENTINEL_PRESENT="true"
            fi
            sudo umount "${MNT_DATA}"
        fi
        rmdir "${MNT_DATA}"
    fi
fi

echo "container_sha256=${CONTAINER_SHA256}"
echo "logical_sha256=${LOGICAL_SHA256}"
echo "esp_sentinel_sha256=${ESP_SENTINEL_SHA256}"
echo "esp_sentinel_present=${ESP_SENTINEL_PRESENT}"
echo "data_sentinel_sha256=${DATA_SENTINEL_SHA256}"
echo "data_sentinel_present=${DATA_SENTINEL_PRESENT}"
