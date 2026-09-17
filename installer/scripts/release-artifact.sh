#!/usr/bin/env bash
# The one canonical artifact-release helper (S7.1R Corrective A/Section
# 7 - mirroring distribution/scripts/record-failure.sh's "one canonical
# helper, never scattered ad-hoc" discipline). Deletes EXACT, already-
# known repo-relative path(s) once their real final consumer has
# finished with them - never a glob, never outside the repository root,
# never via sudo (every path this releases is owned entirely by this
# job's own unprivileged build/dist workspace, not the qemu-nbd-backed
# fixture disks, which have their own root-confined cleanup inside
# create-fixture-disks.sh).
#
# Fails closed if a given path is absolute, contains a `..` traversal
# segment, or resolves (after symlink resolution) outside the
# repository root - never follows a symlink out of the workspace.
# Silent no-op for any path that does not exist (Section 28 - a
# storage-lifetime release step must never fail merely because an
# earlier stage's own failure means the artifact was never created).
#
# Usage: ./installer/scripts/release-artifact.sh <repo-relative-path> [<repo-relative-path> ...]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <repo-relative-path> [<repo-relative-path> ...]" >&2
    exit 1
fi

for target in "$@"; do
    case "${target}" in
        /*|*..*)
            echo "::error::refusing to release non-relative or traversal-looking path: ${target}" >&2
            exit 1
            ;;
    esac

    if [ ! -e "${target}" ]; then
        echo "already absent, nothing to release: ${target}"
        continue
    fi

    resolved="$(realpath -m "${target}")"
    case "${resolved}" in
        "${REPO_ROOT}"/*) ;;
        *)
            echo "::error::refusing to release ${target} - resolves outside the repository root" >&2
            exit 1
            ;;
    esac

    size="$(du -sh "${target}" 2>/dev/null | cut -f1 || echo '?')"
    echo "releasing ${target} (${size})"
    rm -rf -- "${target}"
done
