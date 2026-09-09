#!/usr/bin/env bash
# Records EVERY secondary/non-blocking failure this workflow's
# diagnostic/cleanup steps encounter (S7.1R6 Objective D) - a full
# audit trail, separate from and additive to
# `distribution/scripts/record-failure.sh`'s own PRIMARY
# `dist/.failure_stage`/`.failure_reason` first-failure-wins mechanism
# (an S7.0-owned helper this pass never modifies - Section 13).
#
# Real Run #6 raised a concern that a real primary installer blocker
# (e.g. `installer_timeout`) could become obscured if a later,
# genuinely secondary cleanup/diagnostic failure (e.g.
# `artifact_release_failed`) is the only failure visible in the
# assembled evidence's `secondary_failures` reporting. This helper
# guarantees the opposite: it NEVER writes to `.failure_stage`/
# `.failure_reason` (the sole source of the evidence's PRIMARY
# `failure_stage`/`failure_reason` fields, computed exclusively by
# `record-failure.sh`, unchanged) - it only APPENDS one line per call
# to `dist/.secondary_failures`, so every diagnostic/cleanup step's
# own failure remains visible in evidence, tagged distinctly as
# secondary, no matter how many occur or in what order.
#
# Usage: ./installer/scripts/record-secondary-failure.sh <stage> <reason>
#
# Format: one `<stage>\t<reason>` line per call (tab-separated - a
# reason may legitimately contain "=" or ":" without ambiguity).
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <stage> <reason>" >&2
    exit 1
fi

STAGE="$1"
REASON="$2"

mkdir -p dist
printf '%s\t%s\n' "${STAGE}" "${REASON}" >> dist/.secondary_failures
