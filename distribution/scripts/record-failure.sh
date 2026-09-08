#!/usr/bin/env bash
# Records the FIRST real Layer-B failure stage/reason (S7.0RM6
# Corrective C/Section 17-18). `dist/.failure_stage`/`.failure_reason`
# are the canonical closure-blocker evidence a real run exposed a
# defect in: multiple independent post-build checks (e.g. strict QA
# inspection, then QEMU boot) can each fail in the SAME job, and a
# later, unrelated failure must never overwrite the FIRST real
# blocker's evidence - a real run recorded `failure_stage=qemu_boot`
# even though strict QA inspection had already failed first, losing
# the actual first causal blocker.
#
# Every step in .github/workflows/iso-smoke.yml that can fail calls
# this ONE canonical helper instead of an ad-hoc
# `echo ... > dist/.failure_stage` - first-failure-wins semantics live
# in exactly one place, never scattered/duplicated per step.
#
# Usage: ./distribution/scripts/record-failure.sh <stage> <reason>
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <stage> <reason>" >&2
    exit 1
fi

STAGE="$1"
REASON="$2"

mkdir -p dist
if [ -f dist/.failure_stage ]; then
    echo "note: dist/.failure_stage already records '$(cat dist/.failure_stage)' -" \
         "keeping it (first-failure-wins); this later failure ('${STAGE}') is not" \
         "recorded as the closure blocker" >&2
else
    echo "${STAGE}" > dist/.failure_stage
    echo "${REASON}" > dist/.failure_reason
fi
