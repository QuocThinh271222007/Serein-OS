#!/usr/bin/env bash
# Fail-closed verification of the cached base ISO (S7.0 Sections 10-11).
#
#   download -> sha256 verify -> only then extract
#
# Never: download -> build anyway. This script must exit non-zero on any
# mismatch, and build-iso.sh must refuse to proceed unless this passes.
#
# Usage: ./distribution/scripts/verify-base-image.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE_DIR="${REPO_ROOT}/cache/upstream"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

echo "==> sha256 verification (fail-closed)"
"${PYTHON_BIN}" -m serein.distribution verify-base

# Optional signature verification (Section 11) - only attempted if gpg
# is installed and the checksum/signature files were fetched alongside
# the ISO. Never hardcodes an unofficial signing key; the expected
# fingerprint comes from distribution/base-image.json
# (signing_key_fingerprint), pinned from a live keyserver.ubuntu.com
# lookup - see docs/distribution/security.md for the exact trust path.
if command -v gpg >/dev/null 2>&1 \
    && [ -f "${CACHE_DIR}/SHA256SUMS" ] \
    && [ -f "${CACHE_DIR}/SHA256SUMS.gpg" ]; then

    FINGERPRINT="$("${PYTHON_BIN}" -c "
import json
from pathlib import Path
data = json.loads(Path('${REPO_ROOT}/distribution/base-image.json').read_text())
print(data['signing_key_fingerprint'])
")"

    echo "==> GPG signature verification (expected signer: ${FINGERPRINT})"
    export GNUPGHOME="${CACHE_DIR}/.gnupg-verify"
    mkdir -p "${GNUPGHOME}"
    chmod 700 "${GNUPGHOME}" 2>/dev/null || true

    curl -fsSL -o "${GNUPGHOME}/signing-key.asc" \
        "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x${FINGERPRINT}"
    gpg --batch --import "${GNUPGHOME}/signing-key.asc"

    if gpg --batch --verify "${CACHE_DIR}/SHA256SUMS.gpg" "${CACHE_DIR}/SHA256SUMS" 2>&1 \
        | grep -q "Good signature"; then
        echo "PASS: SHA256SUMS signature verified against pinned key ${FINGERPRINT}"
    else
        echo "FAIL: SHA256SUMS signature did not verify against pinned key ${FINGERPRINT}" >&2
        exit 1
    fi
else
    echo "SKIP: gpg or checksum/signature files not present - signature verification not performed"
fi

echo "Base image verification complete."
