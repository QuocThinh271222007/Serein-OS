#!/usr/bin/env bash
# Real, read-only measurement of the protected fixture disk (S7.1R4
# Section 8-9) - separately measures three distinct facts that the
# workflow's pre-existing plain `sha256sum <file>` container hash
# alone cannot distinguish between:
#
#   protected_container_sha256 - sha256 of the raw qcow2 FILE (the
#     EXISTING measurement this workflow has always taken). Real
#     Run #3 and Run #4 both showed this changing - but a qcow2
#     container's bytes can change from the format's own internal
#     bookkeeping (lazy refcounts, dirty-bit state on open/close)
#     purely from being opened for WRITE access, even with zero
#     guest-visible content change. This measurement alone cannot
#     distinguish that from a real write.
#
#   protected_logical_sha256 - sha256 of the FULL guest-visible
#     logical block content, read via a read-only qemu-nbd
#     connection (never a partial read, never a mount) - proves
#     whether the bytes a guest OS would actually see changed,
#     independent of qcow2's own container-format metadata. Section
#     8's central distinction: "container SHA changed + logical raw
#     SHA unchanged" (container-level-only mutation) is a materially
#     different, less alarming finding than "container SHA changed +
#     logical raw SHA changed" (real guest-visible block mutation).
#
#   protected_esp_sentinel_sha256 / protected_data_sentinel_sha256 -
#     sha256 of the two real sentinel files
#     create-fixture-disks.sh writes (EFI/Microsoft/Boot/sentinel.txt
#     on the FAT32 ESP, SENTINEL.txt on the ext4 data partition) - an
#     additional, filesystem-level integrity marker distinct from the
#     raw logical-block hash above.
#
# This script NEVER writes to the protected image. qemu-nbd is
# connected with --read-only throughout; the ESP mount is a plain
# read-only FAT32 mount (no journal to replay); the ext4 data mount
# uses `-o ro,noload` specifically so a read-only mount can never
# silently replay a dirty ext4 journal onto the block device (Section
# 8: "do not mount protected filesystems read-write merely to inspect
# them" - noload is the extra step that makes a READ-ONLY mount
# itself provably non-mutating too).
#
# Usage: ./installer/scripts/hash-protected-disk.sh <protected-qcow2>
#
# Prints, to stdout, lines suitable for `>> "$GITHUB_OUTPUT"`:
#   protected_container_sha256=<hex>
#   protected_logical_sha256=<hex>
#   protected_esp_sentinel_sha256=<hex-or-empty>
#   protected_esp_sentinel_present=true|false
#   protected_data_sentinel_sha256=<hex-or-empty>
#   protected_data_sentinel_present=true|false

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <protected-qcow2>" >&2
    exit 1
fi
PROTECTED_IMG="$1"

for cmd in sha256sum qemu-nbd blkid partprobe dd; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "::error::${cmd} is required to hash the protected disk" >&2
        exit 1
    fi
done

CONTAINER_SHA256="$(sha256sum "${PROTECTED_IMG}" | cut -d' ' -f1)"

sudo modprobe nbd max_part=8
NBD_DEV="/dev/nbd3"

sudo qemu-nbd --connect="${NBD_DEV}" --read-only "${PROTECTED_IMG}"
trap 'sudo qemu-nbd --disconnect "${NBD_DEV}" >/dev/null 2>&1 || true' EXIT
sleep 1
sudo partprobe "${NBD_DEV}" || true
sleep 1

# The full guest-visible logical block content - a raw byte-for-byte
# read via the read-only nbd device, never a mount.
LOGICAL_SHA256="$(sudo dd if="${NBD_DEV}" bs=1M status=none | sha256sum | cut -d' ' -f1)"

ESP_SENTINEL_SHA256=""
ESP_SENTINEL_PRESENT="false"
if [ -b "${NBD_DEV}p1" ]; then
    P1_TYPE="$(sudo blkid -o value -s TYPE "${NBD_DEV}p1" 2>/dev/null || echo "")"
    if [ "${P1_TYPE}" = "vfat" ]; then
        MNT_ESP="$(mktemp -d)"
        if sudo mount -o ro "${NBD_DEV}p1" "${MNT_ESP}" 2>/dev/null; then
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
if [ -b "${NBD_DEV}p2" ]; then
    P2_TYPE="$(sudo blkid -o value -s TYPE "${NBD_DEV}p2" 2>/dev/null || echo "")"
    if [ "${P2_TYPE}" = "ext4" ]; then
        MNT_DATA="$(mktemp -d)"
        # `noload`: never replay a dirty ext4 journal, even under a
        # read-only mount - guarantees this measurement cannot itself
        # be a mutation vector.
        if sudo mount -o ro,noload "${NBD_DEV}p2" "${MNT_DATA}" 2>/dev/null; then
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

sudo qemu-nbd --disconnect "${NBD_DEV}"
trap - EXIT

echo "protected_container_sha256=${CONTAINER_SHA256}"
echo "protected_logical_sha256=${LOGICAL_SHA256}"
echo "protected_esp_sentinel_sha256=${ESP_SENTINEL_SHA256}"
echo "protected_esp_sentinel_present=${ESP_SENTINEL_PRESENT}"
echo "protected_data_sentinel_sha256=${DATA_SENTINEL_SHA256}"
echo "protected_data_sentinel_present=${DATA_SENTINEL_PRESENT}"
