#!/usr/bin/env bash
# Lightweight disk-usage telemetry (S7.1R Section 10) - logs available/
# used space plus `du -sh` for whichever of the named large artifacts
# currently exist. Never fails merely because an optional path is
# already gone - most of these ARE expected to be gone by later stages,
# once their own release step has run (see installer-smoke.yml's
# storage-lifetime cleanup steps).
#
# Usage: ./installer/scripts/log-disk-usage.sh <stage-label>

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

STAGE="${1:?stage label required}"

echo "=== disk usage: ${STAGE} ==="
AVAILABLE_KB="$(df -Pk . | tail -1 | awk '{print $4}')"
USED_KB="$(df -Pk . | tail -1 | awk '{print $3}')"
echo "available_kb=${AVAILABLE_KB}"
echo "used_kb=${USED_KB}"

for path in \
    cache/upstream \
    build/work \
    build/installer-work \
    dist/serein-alpha-26.04-amd64.iso \
    dist/serein-alpha-26.04-amd64-qa.iso \
    dist/serein-alpha-26.04-amd64-qa-install.iso \
    dist/installer-fixtures \
    ; do
    if [ -e "${path}" ]; then
        du -sh "${path}" 2>/dev/null | sed "s|^|  |" || true
    fi
done
echo "=== end disk usage: ${STAGE} ==="
