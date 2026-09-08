#!/usr/bin/env bash
# Narrowly scoped extraction of installer-relevant lines from the real
# QEMU guest serial log (S7.1R4 Section 10) - never a large new
# framework, just a targeted grep so the NEXT real run's evidence
# already highlights the handful of lines that actually matter
# (Subiquity/curtin/autoinstall/cloud-init activity, tracebacks,
# explicit error/warning messages) without requiring a human to
# manually search a 400+KB raw serial transcript by hand every time a
# real run needs diagnosing.
#
# Usage: ./installer/scripts/extract-installer-signals.sh <serial-log> <output-path>
#
# Never fails if no matching lines exist, and never fails if the
# serial log itself does not exist (e.g. QEMU died before the guest
# ever opened its console) - writes an explicit, honest marker instead
# in either case. This is a diagnostic convenience only, never a gate
# - it must never affect installation_status/failure_stage.

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <serial-log> <output-path>" >&2
    exit 1
fi
SERIAL_LOG="$1"
OUTPUT="$2"

mkdir -p "$(dirname "${OUTPUT}")"

if [ ! -f "${SERIAL_LOG}" ]; then
    echo "no serial log present at ${SERIAL_LOG}" > "${OUTPUT}"
    exit 0
fi

if ! grep -Ein \
    'subiquity|curtin|autoinstall|cloud-init|nocloud|ds=nocloud|Traceback|Exception|storage.*match|ERROR|WARN' \
    "${SERIAL_LOG}" > "${OUTPUT}" 2>/dev/null; then
    echo "no subiquity/curtin/autoinstall/cloud-init/error lines found in ${SERIAL_LOG}" \
        > "${OUTPUT}"
fi
