# AI Model/Cache Storage Strategy

See ADR-0016 for the full decision record.

## No new, unified data root

S4 does not invent a `/data`-style layout or assume a dedicated volume
exists — that is S7's job, once a real deployment target exists (S4
brief Section 45/46). Instead, `storage.py` reports where each tool's
*own* existing convention already points:

- **Hugging Face**: `HF_HOME` (current canonical env var; `HF_HUB_CACHE`
  is a more specific override, `TRANSFORMERS_CACHE` is legacy/deprecated
  and not used by Serein). Default if unset: `~/.cache/huggingface`.
- **Ollama**: `OLLAMA_MODELS` env var if set, else Ollama's own default
  (`~/.ollama/models`).

Neither is relocated by Serein — `hf_home_is_default`/
`ollama_models_is_default` simply report whether the user has already
customized it.

## Privacy-safe path normalization

Every path field on `AIStorageInfo` is normalized (the real home
directory prefix replaced with `~`) *before* being stored — this
happens inside `storage.py`, not at the CLI print layer, so there is
no code path that can accidentally leak the real absolute home
directory/username through this struct. See the privacy regression
tests in `tests/test_ai.py::TestPrivacy`.

## Free-space checking

A lightweight `shutil.disk_usage()` call against the nearest existing
ancestor of the Hugging Face cache path — not a re-implementation of
S2's block-device probing (which reports raw device capacity, not a
specific path's free space; the two answer different questions).
`low_space_warning` fires below a conservative 5 GiB floor (documented
in `storage.py` — a handful of quantized 7-8B GGUF models already run
4-6 GiB each) and only ever influences a `WARN`-level signal, never
blocks planning.

## What this module never does

Never enumerates model filenames, dataset names, or private repository
names — `serein ai status`'s Storage section reports only aggregate
paths/policy, matching S4 brief Section 49's privacy requirement.
