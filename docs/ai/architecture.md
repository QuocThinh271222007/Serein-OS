# S4 — AI Workstation Architecture

## Governing question

> What AI compute backend can this machine genuinely use, what runtime
> stack already exists, what stack is compatible with the hardware and
> workload, and what should be provisioned without destabilizing the
> operating system?

S4 answers this without installing a driver, a toolkit, a Python
package, or downloading a single model byte. It is the same
three-layer model S2 (hardware) and S3 (development) established,
applied to AI:

```
serein ai status         read-only: what already exists
serein ai capabilities   what Serein could safely provision, and
                         whether the underlying runtime is *usable*
serein ai plan           a deterministic, never-executed install plan
serein ai doctor         profile/manifest/plan integrity + conflicts
```

## The three-layer distinction (never collapsed)

The single most important invariant in this subsystem, repeated
throughout every module's docstring because it is also the single
easiest mistake to make:

```
hardware present  ≠  driver/runtime installed  ≠  actually usable
```

A GPU showing up in `/sys/class/drm` proves nothing about CUDA. A
driver reporting a "CUDA Version" in `nvidia-smi`'s banner proves
nothing about whether the CUDA *Toolkit* is installed. AMD hardware
existing proves nothing about ROCm support for that exact chip. Every
detector in `serein/ai/` keeps these as separate fields precisely so a
caller cannot accidentally read one as evidence for the other — see
`nvidia.py`'s and `amd.py`'s module docstrings for the specific
mechanics.

## Module map

```
src/serein/ai/
├── models.py       dataclasses only — AIBackendInfo, NvidiaStatus,
│                   AmdStatus, IntelAIStatus, PyTorchStatus,
│                   PythonAIPackagesStatus, InferenceStatus,
│                   AIContainerStatusInfo, AIStorageInfo,
│                   AICapability/AIPlanAction and their report wrappers
├── backend.py      classify_backend() — consumes S2's GPUDevice list/
│                   GPUPolicyInfo, never re-probes hardware
├── nvidia.py        driver/CUDA-driver-API/CUDA-Toolkit/VRAM/
│                   container-toolkit detection
├── amd.py          ROCm support via real rocminfo runtime evidence
├── intel.py        Intel GPU topology + honest maturity label
├── python_env.py   importlib.metadata-based Python-AI-package probes
├── pytorch.py      PyTorch build-variant detection (subprocess import,
│                   never torch.cuda.is_available())
├── inference.py    Ollama + llama.cpp detection
├── containers.py   reuses S3's container detection + NVIDIA Container
│                   Toolkit/CDI marker
├── storage.py      HF_HOME/OLLAMA_MODELS convention reporting, never
│                   a new unified data root
├── packages.py     the declarative tool/source manifest (reuses S3's
│                   ToolDefinition)
├── capabilities.py build_ai_capabilities() — the 16-capability report
├── planner.py      build_ai_plan() — the canonical, filterable plan
├── status.py       build_ai_status() — read-only summary
└── doctor.py       run_ai_checks() — profile/manifest/plan/conflict
                    integrity, PASS/WARN/FAIL/SKIP
```

## Why this reuses S3 rather than forking a parallel system

Per the S4 brief's Section 86, S4 imports `ToolDefinition`, `ToolStatus`,
and `CommandRunner` from `serein.development.models`/`runner` directly.
`packages.py` extends S3's `source_type` taxonomy with exactly one new,
documented value (`"python-package-index"`, for `uv`-installed PyPI/
framework-index packages) rather than inventing a second taxonomy.
`containers.py` calls `serein.development.containers.detect_container_status`
directly rather than re-probing podman/docker/distrobox. This mirrors
the same reasoning S3 itself used when it reused S2's `EnvironmentInfo`/
`detect_environment` for container-nesting detection.

## No Apply mechanism

Exactly like S3, no `serein ai apply` command exists. Every
`AIPlanAction` is `APPLY`/`NOOP`/`SKIP`/`BLOCKED` and nothing more —
the action is described, never executed. See docs/ai/known-limitations.md
for what a future Apply engine would need (supply-chain verification in
particular becomes materially more important once non-Ubuntu-repository
sources — NVIDIA's/AMD's own apt repos, PyPI wheel indexes, GitHub
Releases binaries — are involved; see docs/ai/security.md).

## Command safety

Every detection command is read-only, timeout-bounded, and run through
the same injectable `CommandRunner` S3 established — `shell=False`
always, no interactive prompts. The forbidden list is explicit and
enforced by regression tests (`tests/test_ai.py::TestForbiddenActions`):
no `model pull`, no `container run`/`create`, no GPU stress test, no
driver install, no daemon start/stop/restart during detection. The one
partial exception, and it is read-only: `pytorch.py` runs
`python3 -c "import torch; ..."` in a *child* process to read
`torch.__version__`/`torch.version.cuda`/`torch.version.hip` — an
ordinary, safe operation that loads shared libraries but never touches
GPU hardware. `torch.cuda.is_available()` is deliberately never called
(see docs/ai/pytorch-strategy.md).

## Installed vs. supported vs. managed

Same as S3: `installed = detected`, never inferred from anything else;
`managed` is not tracked at all (no Apply engine exists yet, so there is
nothing for Serein to have applied). Doctor never FAILs merely because
an AI stack isn't installed — see docs/ai/known-limitations.md and each
module's own conflict-handling notes.

## Conflict handling

Multiple CUDA Toolkit directories, an AMD GPU ROCm has confirmed
unsupported, and both Podman and Docker installed are all `WARN`
territory for the doctor, never `FAIL` — S4 does not treat a user's
existing, working setup as broken. See `doctor.py`'s module docstring.
