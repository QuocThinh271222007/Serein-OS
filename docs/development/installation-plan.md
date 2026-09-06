# Development Installation Plan

Mirrors `docs/desktop/installation-plan.md`'s mapping onto the S0
installer lifecycle (Discover → Resolve → Plan → Validate → Apply →
Verify → Record).

| Lifecycle step | S3 status |
|---|---|
| Discover | Implemented — `serein dev status`/`capabilities` (git.py, python.py, node.py, rust.py, go.py, cpp.py, editor.py, containers.py). |
| Resolve | Implemented — conflict detection (multiple Node managers, multiple container engines, existing Python managers). |
| **Plan** | Implemented — `serein dev plan [component]`, deterministic, capability-gated. |
| Validate | Not implemented — no pre-flight dependency/checksum verification exists yet. |
| Apply | Not implemented — no `serein dev apply` command exists, by design (Section 12 of the S3 brief). |
| Verify | Not implemented — depends on Apply existing first. |
| Record | Not implemented — no managed-state marker file exists yet (unlike S1's desktop config-version marker); nothing has been applied to record. |

## Example `serein dev plan python` output

```
SEREIN DEVELOPMENT PLAN - python

  [APPLY  ] python.install_tool: uv -> latest (current: not installed)
            reason: Serein prefers uv for project-local Python environments...
            risk: low | reversible: yes | requires_root: no | source: official-upstream-binary
            verify: uv --version
  [NOOP   ] python.report_only: pyenv/conda/micromamba (current: none)
            reason: No other Python environment manager detected.
            risk: none | reversible: yes | requires_root: no | source: None
            verify: n/a
```

## Determinism

`build_development_plan()` is a pure function of on-disk/PATH state at
call time: given the exact same tool/config state, it returns
byte-identical output on every call (verified by
`tests/test_development.py`'s determinism test).
