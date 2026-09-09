#!/usr/bin/env bash
# Create the two S7.1 Layer-B fixture disk images (Sections 30-32):
#
#   disk-protected.qcow2 - simulates an internal disk that MUST survive
#     completely untouched by installation: a GPT with a FAT32 ESP
#     containing a Microsoft-style sentinel path (EFI/Microsoft/Boot/ -
#     Section 31, "exercise Windows classification... simple sentinel
#     data is enough, no need to ship Microsoft binaries") plus an ext4
#     data partition with its own sentinel file.
#
#   disk-target.qcow2 - simulates the external installation target,
#     PRE-POPULATED with an existing layout (a GPT + an existing ext4
#     partition with sentinel data, standing in for Section 32's
#     "OLD_DEBIAN_DATA") - so a real install proves Serein intentionally
#     REPLACES a pre-existing layout only after explicit targeting,
#     never merely writing to a conveniently blank disk.
#
# Ephemeral GitHub-hosted-runner setup only (Section 21 distinguishes
# this from target-host mutation) - every operation here is against a
# brand-new qcow2 FILE created inside the CI workspace, NEVER a real
# host block device (Section 49-50: REAL_PHYSICAL_DISK_PASSTHROUGH=false
# is enforced by construction - this script never references /dev/sdX
# or any physical device path, only qemu-nbd loopback devices against
# files this script itself just created).
#
# Usage: ./installer/scripts/create-fixture-disks.sh <output-dir>
#
# Requires root (via sudo) to bind qemu-nbd/mount - real Layer-B CI
# only; never run against a developer's real machine.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <output-dir>" >&2
    exit 1
fi
OUT_DIR="$1"
mkdir -p "${OUT_DIR}"

for cmd in qemu-img qemu-nbd parted mkfs.vfat mkfs.ext4 partprobe; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "::error::${cmd} is required to build S7.1 Layer-B fixture disks" >&2
        exit 1
    fi
done

sudo modprobe nbd max_part=8

# _populate_disk <image-path> <size> <nbd-device> <data-label> <sentinel-text>
_populate_disk() {
    local img="$1" size="$2" nbd_dev="$3" data_label="$4" sentinel_text="$5"

    qemu-img create -f qcow2 "${img}" "${size}"

    sudo qemu-nbd --connect="${nbd_dev}" "${img}"
    # shellcheck disable=SC2064
    trap "sudo qemu-nbd --disconnect '${nbd_dev}' >/dev/null 2>&1 || true" RETURN
    sleep 1

    sudo parted -s "${nbd_dev}" mklabel gpt
    sudo parted -s "${nbd_dev}" mkpart ESP fat32 1MiB 129MiB
    sudo parted -s "${nbd_dev}" set 1 esp on
    sudo parted -s "${nbd_dev}" mkpart data ext4 129MiB 100%
    sync
    sudo partprobe "${nbd_dev}"
    sleep 1

    sudo mkfs.vfat -F32 -n SENTINELESP "${nbd_dev}p1"
    sudo mkfs.ext4 -F -L "${data_label}" "${nbd_dev}p2"

    local mnt_esp mnt_data
    mnt_esp="$(mktemp -d)"
    mnt_data="$(mktemp -d)"
    sudo mount "${nbd_dev}p1" "${mnt_esp}"
    sudo mount "${nbd_dev}p2" "${mnt_data}"

    sudo mkdir -p "${mnt_esp}/EFI/Microsoft/Boot" "${mnt_esp}/EFI/Boot"
    echo "${sentinel_text} - ESP - do not modify" \
        | sudo tee "${mnt_esp}/EFI/Microsoft/Boot/sentinel.txt" >/dev/null
    echo "${sentinel_text} - data - do not modify" \
        | sudo tee "${mnt_data}/SENTINEL.txt" >/dev/null

    sudo umount "${mnt_esp}"
    sudo umount "${mnt_data}"
    rmdir "${mnt_esp}" "${mnt_data}"

    sudo qemu-nbd --disconnect "${nbd_dev}"
    trap - RETURN
}

echo "==> Creating protected disk fixture (${OUT_DIR}/disk-protected.qcow2)"
_populate_disk \
    "${OUT_DIR}/disk-protected.qcow2" 4G /dev/nbd0 \
    "PROTECTED_DATA" "SEREIN_PROTECTED_FIXTURE"

# S7.1R6 Objective B: 16G (was 8G) - real project evidence
# (docs/installer/storage-lifecycle.md's own documented QA_ISO_GIB=7
# estimate for Serein's built Ubuntu 26.04 Desktop QA ISO; base
# ISO ~6.0 GB per distribution/base-image.json's own recorded notes)
# means the compressed source payload alone is already ~6-7 GiB - a
# real full-desktop install's DECOMPRESSED root filesystem footprint
# is virtually always larger than its compressed source, never
# smaller, so the previous 8G target left essentially no real margin.
# 16G is a bounded, evidence-informed increase - still a realistic
# constrained installation target, never made absurdly large merely to
# guarantee CI success.
echo "==> Creating target disk fixture (${OUT_DIR}/disk-target.qcow2)"
_populate_disk \
    "${OUT_DIR}/disk-target.qcow2" 16G /dev/nbd1 \
    "OLD_DEBIAN_DATA" "SEREIN_TARGET_FIXTURE_PRE_INSTALL"

echo "==> Recording pre-install fixture disk hashes"
sha256sum "${OUT_DIR}/disk-protected.qcow2" | tee "${OUT_DIR}/disk-protected.sha256-before"
sha256sum "${OUT_DIR}/disk-target.qcow2" | tee "${OUT_DIR}/disk-target.sha256-before"
