# AI Security Policy

AI introduces a materially different threat model than S1-S3's
integration work: model files are untrusted input, and several common
model-loading mechanisms can execute arbitrary code from a downloaded
artifact.

## `trust_remote_code` is never enabled by Serein

Hugging Face's `transformers`/`huggingface_hub` support a
`trust_remote_code=True` flag that allows a model repository to ship
and execute its own Python code on load. **Serein never enables this
by default, in any documentation, template, or (future) Apply
behavior.** This is enforced as a direct test invariant
(`tests/test_ai.py::TestForbiddenActions::test_no_trust_remote_code_mentioned_as_enabled`)
scanning every plan action's reason text for the literal enabling
pattern. A user/project may opt in for a specific, trusted model — that
decision belongs to the project, never to a Serein default.

## Pickle vs. safetensors

`safetensors` is the preferred serialization format where a model
provides it (no deserialization-time code execution, unlike Python's
`pickle`, which `.pth`/`.bin` checkpoints commonly use). This is **not**
a blanket claim that `.pth` files are unusable — Eirune's voice/RVC
workload class may genuinely need pickle-based checkpoints — only that
pickle-based formats require a trusted source, and Serein documents
this rather than pretending the risk doesn't exist.

## No automatic model downloads

`serein ai plan` never proposes `ollama pull`, `huggingface_hub`
downloads, or a raw `wget <model-url>` as a plan action. S4 plans
*runtime/tool* installation only — a model file crossing the network
is always a separate, explicit, user-initiated action outside Serein's
scope (S4 brief Section 81).

## Supply-chain posture for non-Ubuntu-repository sources

S4's manifest introduces materially more non-Ubuntu-archive sources
than S3 did: NVIDIA's own apt repo (CUDA Toolkit, NVIDIA Container
Toolkit), AMD's own apt repo (ROCm), PyPI/PyTorch's own wheel index
(torch, transformers, vllm, ...), and GitHub Releases binaries
(Ollama's installer script, llama.cpp prebuilt assets). Every one of
these is represented declaratively — never executed — with its exact
mechanism documented in `packages.py`. A future Apply engine should
prefer, in this order: an official repository with package signing
already verified by `apt`, a checksummed/signed release asset, over an
opaque `curl | sh` pattern used as final architecture (the S4 brief's
own Section 57 guidance) — this is the beginning of a formalized
trust model, not the finished thing; full signature-chain verification
is deferred, likely to S7.

## Telemetry

Serein introduces none, and does not enable any AI framework's own
analytics/telemetry by default (several — including some inference
servers — ship opt-out telemetry; Serein's plan actions never turn it
on).

## Credentials

`serein ai status`/`doctor`/`capabilities` never inspect or store
Hugging Face tokens, API keys, or any other credential — every command
works fully offline and unauthenticated. This mirrors S3's identical
policy for GitHub CLI authentication.
