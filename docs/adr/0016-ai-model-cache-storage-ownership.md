# ADR-0016: AI Model/Cache Storage Ownership

## Status

Accepted

## Context

AI workloads accumulate large model/dataset caches (GGUF files,
Hugging Face model snapshots, Ollama's own store). S7 will eventually
own real filesystem/data-volume deployment; S4 must define a logical
storage convention now without assuming a dedicated volume exists yet
(S4 brief Section 45/46), and without leaking the developer's real
home directory path through any status/JSON output.

## Decision

- **No new, unified Serein-owned data root is introduced in S4.**
  Instead, `storage.py` reports where each tool's *own* existing
  convention already points: Hugging Face's `HF_HOME` (current
  canonical env var — `HF_HUB_CACHE` is a more specific override,
  `TRANSFORMERS_CACHE` is legacy/deprecated) and Ollama's
  `OLLAMA_MODELS`. Neither is relocated.
- **Every reported path is normalized** (`~`-relative) inside
  `storage.py` before being stored on `AIStorageInfo` — never at the
  CLI print layer — so no code path can leak the real absolute home
  directory/username.
- **Free-space checking** is a lightweight `shutil.disk_usage()` call
  against the Hugging Face cache path's nearest existing ancestor, not
  a re-implementation of S2's raw block-device-capacity probing (a
  different, path-specific question). A conservative 5 GiB floor
  triggers `low_space_warning` — informational only, never blocking.
- **No model/dataset enumeration** — `serein ai status`'s Storage
  section reports only aggregate paths/policy, per the S4 brief's
  explicit privacy requirement (Section 49).

## Alternatives considered

- **A Serein-specific `SEREIN_AI_MODEL_ROOT`-style env var**: rejected
  — inventing a new storage convention before S7 provisions a real
  deployment target adds complexity without a concrete consumer;
  each tool's own existing, well-known convention is sufficient for
  S4's detection/reporting scope.
- **Hardcoding `/data/ai-models/...`**: rejected outright per the S4
  brief's explicit instruction (Section 46) — no evidence that path
  exists on an arbitrary target machine.

## Consequences

- S4's storage reporting is honest about being a convention summary,
  not a real deployment — `docs/ai/known-limitations.md` states this
  plainly.
- When S7 eventually provisions a dedicated data volume, this module's
  `AIStorageInfo` shape is a natural place to add a "recommended
  Serein data root" concept then — deliberately deferred, not designed
  in now without a concrete requirement.
