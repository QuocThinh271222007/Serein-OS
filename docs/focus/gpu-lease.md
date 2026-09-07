# GPU Lease Intent

## Why "lease intent", never "GPU cgroup owner"

Linux has no universal, cross-vendor equivalent of "GPU cgroup owner"
(Section 29). NVIDIA, AMD, and Intel each expose GPU resource control
through entirely different, vendor-specific mechanisms (if at all);
there is no generic kernel/systemd primitive analogous to CPUWeight
for GPU compute. Pretending otherwise would be exactly the kind of
overclaim S6.5's own quality bar forbids. `GPULeaseIntent.enforceable`
is therefore `False` in every build this codebase produces, regardless
of target or hardware - regression-tested directly
(`tests/test_focus.py::TestGpuLeaseIntent::test_gpu_never_enforceable`,
`serein focus doctor`'s `focus_gpu_not_overclaimed` check).

## Lease modes (Section 30)

```python
GPU_LEASE_MODES = ("preferred", "shared", "release_requested", "unavailable", "unknown")
```

`"exclusive"` is deliberately never a value here - it would imply real
backend enforcement, which does not exist. `resources.build_gpu_intent()`
picks a mode from real evidence:

```
No GPU device detected (S2 evidence)          -> "unavailable"
AI is primary AND a GPU is present             -> "preferred", preferred_domain="ai"
(everything else)                               -> "shared", preferred_domain=None
```

## Per-domain policy (Section 31-34)

- **AI** (Section 31): the only domain whose primary focus moves the
  mode to `"preferred"` - and even then only when S2 evidence actually
  shows a GPU device; `enforceable` stays `False` regardless.
- **Cyber** (Section 32): never automatically claims the GPU merely
  because it became primary - most cyber workflows (host diagnostics,
  packet capture, VM/toolbox management) are not GPU-heavy, and S6.5
  has no live evidence of a GPU-bound tool (e.g. `hashcat`) actually
  running, so the mode stays `"shared"`.
- **Dev** (Section 33): stays `"shared"` by default - development does
  not prioritize GPU access simply because it is the current focus; a
  future phase with real workload evidence (a compute/render task)
  could change this deliberately.
- **Private** (Section 34): never seeks GPU preference or passthrough
  for performance - isolation/security correctness dominates
  throughput for this domain by design; a Whonix path in particular
  does not need passthrough, and S6.5 never recommends it.

## VRAM cannot be reclaimed by a weight (Section 35)

Unlike CPU/IO/memory, VRAM has no declarative "soft pressure"
equivalent - reclaiming it genuinely requires model unload, process
exit, or runtime eviction. A transition's lifecycle candidates may
mark the AI runtime `QUIESCE_CANDIDATE`, but the transition plan's
`expected_vram_reclaim_bytes` is always `None` - reclaimed VRAM is
never stated unless actually measured, which S6.5 has no mechanism to
do (see `docs/focus/transition-model.md`).

## Conflicts (Section 59-60)

`resources.build_conflicts()` only ever produces a `FocusConflict`
entry from `gpu_intent.conflicting_domains`, which S6.5 never
populates today (no live GPU-utilization evidence exists to name a
genuine conflicting domain) - so the conflict list is empty in every
current build, honestly, rather than fabricated
(`tests/test_focus.py::TestConflictModel::test_no_fabricated_conflicts_without_evidence`).
If a future phase adds real utilization evidence, the resolution text
is constrained to stay non-destructive ("GPU stays shared; no domain
is forcibly evicted").
