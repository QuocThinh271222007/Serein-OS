# ADR-0028: GPU Ownership Is Intent, Not Generic Enforceable State

## Status

Accepted

## Context

Unlike CPU/I/O, Linux has no cross-vendor kernel/cgroup primitive
analogous to "GPU cgroup owner" - NVIDIA, AMD, and Intel each expose
GPU resource control (if at all) through entirely separate,
vendor-specific runtimes with no common interface. A focus model that
claimed `gpu_owner=AI` the way it can claim `cpu_weight=1000` would be
asserting a capability that simply does not exist generically on
Linux today. This matters especially for AI focus, where GPU
preference is the single most consequential resource decision a focus
change could make - and precisely where the temptation to overclaim
enforcement is strongest.

## Decision

- `GPULeaseIntent.enforceable` is `False` in every policy this
  codebase produces, for every target, regardless of hardware -
  enforced directly by `serein focus doctor`'s
  `focus_gpu_not_overclaimed` check and
  `tests/test_focus.py::TestGpuLeaseIntent::test_gpu_never_enforceable`.
- Lease modes are limited to `preferred`/`shared`/`release_requested`/
  `unavailable`/`unknown` - `"exclusive"` is deliberately never a
  value, since it would imply real backend enforcement.
- AI is the only domain whose primary focus moves the mode toward
  `"preferred"`, and only when a GPU device is actually present (S2
  evidence) - Cyber never automatically claims the GPU merely by
  becoming primary (most cyber workflows are not GPU-heavy and S6.5
  has no live evidence of a GPU-bound tool actually running), Dev stays
  shared by default, and Private never seeks GPU preference or
  passthrough, since isolation/security correctness dominates
  throughput for that domain by design.
- VRAM reclaim is never stated as a byte count - VRAM cannot generally
  be reclaimed by a declarative weight the way CPU/memory pressure can
  be signaled; real reclaim requires model unload/process exit/runtime
  eviction, none of which S6.5 performs or measures.

## Consequences

- No consumer of `serein focus plan ai` can mistake `preferred_domain:
  ai` for a working guarantee - the same JSON payload always also
  carries `enforceable: false` and a `mechanism` field explaining why.
- A future phase adding real vendor-specific GPU enforcement (e.g. an
  NVIDIA MPS-aware adapter) has a clean extension point:
  `enforceable` flips to `True` only for the specific vendor/mechanism
  combination that phase actually implements, never generically.
- Cyber/Dev/Private focus never accidentally starve AI (or each other)
  of GPU access through an over-eager default preference - `"shared"`
  stays the safe default absent concrete evidence otherwise.

## Alternatives considered

**Claim `enforceable=True` when NVIDIA hardware + driver is present,
since NVIDIA has some vendor-specific mechanisms.** Rejected - even
where a vendor-specific mechanism exists, S6.5 does not implement or
verify it; claiming enforceability without implementing enforcement is
exactly the overclaim this ADR exists to prevent. A future phase can
make this claim honestly once it actually wires up a vendor adapter.

**Model GPU preference as a CPU-style relative weight instead of a
distinct lease-intent shape.** Rejected - GPU access is fundamentally
different from CPU/IO contention (no generic kernel scheduler mediates
it, and "shared" GPU access has real technical limits a weight cannot
express), so a dedicated `GPULeaseIntent` shape with its own mode
vocabulary was judged clearer than forcing GPU into the CPU/IO weight
model.
