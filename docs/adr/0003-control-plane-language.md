# ADR-0003: Python for the S0 Control-Plane CLI

## Status

Accepted

## Context

Serein needs a CLI/control-plane for hardware discovery, diagnostics, and
(eventually) profile application. The implementation language affects
development speed, dependency surface, portability, and how easily the
project can attract early contributors.

## Decision

Implement the S0 control-plane CLI in **Python (3.12+)**, standard-library
first, with a near-zero runtime dependency surface (`pyproject.toml`
declares no runtime dependencies as of S0). Development/test tooling
(`pytest`, `jsonschema`, `ruff`, `mypy`) is a separate, non-runtime
concern.

Reasons:

- Python ships on virtually every target Ubuntu install already, and its
  standard library (`argparse`, `pathlib`, `dataclasses`, `json`,
  `platform`) covers everything S0 needs without adding dependencies.
- Fast iteration matters more than raw performance at this stage — S0 is
  about establishing correct contracts (schemas, CLI shape, doctor
  semantics), not about a performance-critical hot path.
- Type hints plus `mypy` give a meaningful correctness net without the
  build complexity of a compiled language.
- A large pool of potential contributors can read and modify Python
  without a specialized toolchain.

## Consequences

- CLI startup latency and any future high-frequency system-probing loop
  will be slower than a compiled alternative. Not a concern for S0's
  command-invocation-per-call usage pattern.
- Packaging Serein for distribution (S7) needs to account for Python
  availability/versioning within the target Ubuntu image, though this is
  a solved problem (Ubuntu ships Python 3 by default).
- `uv` may be documented as the preferred *developer* environment manager
  (fast venv/dependency management) without runtime code ever depending on
  it — a contributor without `uv` must still be able to `pip install -e
  .[dev]` and run everything.

## When Rust (or another compiled language) would be reconsidered

This decision should be revisited, per Integrate → Measure → Replace, if a
future phase demonstrates a concrete need Python cannot reasonably meet:

- A component that must run before Python is available at all (e.g. an
  early-boot or initramfs-stage tool).
- A measured performance bottleneck in a hot path (e.g. a background
  daemon doing continuous hardware polling) that Python cannot meet even
  after optimization.
- A requirement to ship a single static binary with no interpreter
  dependency for a specific distribution artifact.

None of these apply to S0's read-only, invoked-on-demand CLI.

## Alternatives considered

- **Rust:** stronger performance/binary-distribution story, but higher
  contribution barrier and slower iteration for a phase focused on
  contract definition rather than performance.
- **Shell (Bash):** rejected as the primary implementation language —
  adequate for `scripts/*.sh` glue, but unsuitable for structured data
  models, schema validation, and the test coverage this contract requires.
- **Go:** reasonable single-binary alternative, but no stronger a case
  than Rust for S0, and less standard-library alignment with the
  JSON/dataclass-heavy contract work.
