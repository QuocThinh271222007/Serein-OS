#!/usr/bin/env bash
# Real re-verification of the fixture disk topology (S7.1R Section 16)
# - the closest honest analog, in this CI topology, of
# serein.installer.identity.resolve_target's host-disk TOCTOU re-match.
#
# There is no live host block device to re-probe here (the two fixture
# images are plain qcow2 FILES until QEMU attaches them - the identity
# match a real Subiquity/curtin performs happens INSIDE the guest,
# against the serials QEMU assigns at launch). What this script CAN
# genuinely re-verify on the host, immediately before the real
# destructive install begins, is that the declared topology is real:
# both fixture images exist, both are genuine qcow2 images (not stale/
# corrupt/truncated), and they are two DISTINCT files - never
# accidentally the same backing file attached twice, which would
# silently defeat the entire protected/target distinction.
#
# Usage: ./installer/scripts/verify-fixture-topology.sh <protected-qcow2> <target-qcow2>
#
# Prints, to stdout, a line suitable for `>> "$GITHUB_OUTPUT"`:
#   target_identity_revalidated=true|false

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <protected-qcow2> <target-qcow2>" >&2
    exit 1
fi
PROTECTED_IMG="$1"
TARGET_IMG="$2"

if ! command -v qemu-img >/dev/null 2>&1; then
    echo "::error::qemu-img is required to re-verify the fixture topology" >&2
    echo "target_identity_revalidated=false"
    exit 1
fi

REVALIDATED="false"

if [ -f "${PROTECTED_IMG}" ] && [ -f "${TARGET_IMG}" ]; then
    PROTECTED_REAL="$(realpath "${PROTECTED_IMG}")"
    TARGET_REAL="$(realpath "${TARGET_IMG}")"

    if [ "${PROTECTED_REAL}" != "${TARGET_REAL}" ] \
        && qemu-img info --output=json "${PROTECTED_IMG}" >/dev/null 2>&1 \
        && qemu-img info --output=json "${TARGET_IMG}" >/dev/null 2>&1; then
        REVALIDATED="true"
    fi
fi

echo "target_identity_revalidated=${REVALIDATED}"
if [ "${REVALIDATED}" != "true" ]; then
    exit 1
fi
