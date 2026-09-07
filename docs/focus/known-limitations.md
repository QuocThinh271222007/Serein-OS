# Focus (S6.5) Known Limitations

## No live validation performed this phase

Like S6/S6R/S6RM, S6.5 was implemented and unit-tested entirely
against injected `FakeCommandRunner`/fixture roots/homes plus the real
S2-S6 detectors running against those fixtures - no live host with a
GPU, KVM, or Tor was used to validate a "GPU present" or "private
available" branch end-to-end. Every branch is unit-tested with
synthetic evidence instead.

## No automatic user-intent detection (Section 66, out of scope)

S6.5 does not detect that Zed is running and infer `dev` focus, does
not detect Ollama and infer `ai` focus, and does not detect Wireshark
and infer `cyber` focus. Automatic intent recognition is explicitly
out of scope for this phase - it can produce surprising, unrequested
behavior, and belongs to a much later, carefully-designed future
phase, if ever.

## No persistence, no daemon (Section 67-68)

`serein focus status`'s `applied_focus` is always `None` - there is no
`/etc/serein/focus`, no `~/.config/serein/focus`, no database, and no
background `serein-focusd` process. Every CLI invocation recomputes
everything from scratch against live S2-S6 evidence.

## GPU conflict detection is empty by design (see `docs/focus/gpu-lease.md`)

`build_conflicts()` can only ever report a conflict if
`gpu_intent.conflicting_domains` is populated, and nothing in this
codebase populates it yet - S6.5 has no live GPU-utilization
evidence (e.g. `nvidia-smi`'s per-process listing) to name a genuine
conflicting domain. The conflict *model* exists and is tested; real
conflict *detection* is future work.

## Lifecycle intents cover exactly four named targets

`resources.build_lifecycle_intents()` only ever produces intents for
`ai_runtime`, `cyber_toolbox`, `cyber_vm`, and `whonix` - the specific
targets S4/S5/S6 already expose stable capability evidence for
(Section 37: "only Serein-owned or explicitly understood services").
A future phase adding a new understood service (e.g. a dev-tier
container/build daemon) would extend this list explicitly, never infer
one from a fuzzy process name.

## `expected_ram_reclaim_bytes`/`expected_vram_reclaim_bytes` are always `None`

By design (Section 84-85/105) - no workload-size measurement mechanism
exists in this codebase. A future phase that wants real reclaim
estimates would need genuine, measured workload evidence (e.g. reading
an AI runtime's own reported model size) before populating these
fields; guessing is explicitly forbidden.

## `cost`/`reversible` are qualitative, not measured

`FocusTransitionPlan.cost` derives from the highest-cost lifecycle
intent in the target policy using a small fixed table
(`low`/`medium`/`high`/`unknown`) - never a fabricated time estimate.
`reversible=True` is a constant in every S6.5 transition (nothing has
actually happened yet); a future runtime executor would need to report
this per-action based on what it actually did.

## Domain readiness thresholds are heuristic, not exhaustive

`policy._ai_readiness()`/`_cyber_readiness()`/`_dev_readiness()`/
`_private_readiness()` each check a small, representative subset of
their subsystem's own capability ids (e.g. AI checks `pytorch_cuda`/
`pytorch_rocm`/`pytorch_cpu`/`ollama`/`llama_cpp`, not every AI
capability S4 exposes). This is a deliberate, documented
simplification - broadening the check set is safe, additive future
work, not a correctness fix.
