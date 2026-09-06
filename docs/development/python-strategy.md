# Python Strategy

See ADR-0009 for the full decision record. Summary:

- **System Python (`/usr/bin/python3`) is Ubuntu-owned and never a
  mutation target.** No plan action, at any confidence level, ever
  proposes `sudo pip install` or a `pip install` targeting the system
  interpreter's `site-packages`/`dist-packages`. This is enforced by
  construction: `planner.py` has no code path that runs `pip` at all —
  the only Python-related plan action installs `uv`.
- **`uv`** is Serein's preferred tool for project environments,
  dependency sync, and per-project Python version management. Official
  installer: `astral.sh/uv/install.sh` (documented, never executed by
  S3). No Ubuntu package exists.
- **Existing `pyenv`/Conda/`micromamba` installs are detected and
  reported (`python.existing_managers` plan action), never removed.**
  `python.py`'s `detect_python_status()` checks `~/.pyenv` and
  `~/miniconda3`/`~/anaconda3` as filesystem markers (existence only —
  never their contents) plus a `conda --version` probe.
- **Micromamba is optional** — offered for projects that specifically
  need the Conda package ecosystem, not part of the default plan.

## Project conventions (documentation only — no scaffolding generator)

A typical Serein-recommended project layout:

```
pyproject.toml
.venv/          (created by `uv sync`, gitignored)
uv.lock
```

Recommended workflow: `uv sync` to materialize a project's environment,
`uv run <command>` to execute within it, `uv tool install <cli-tool>`
for globally-available CLI utilities (uv's `pipx`-equivalent). Serein
does not generate `pyproject.toml` templates or enforce a particular
dependency stack — every project chooses its own.

## Cache locations (documented, not moved)

`uv`'s cache lives under `$XDG_CACHE_HOME/uv` (or `~/.cache/uv` if
unset) by uv's own default — Serein does not relocate it. Disk/caching
optimization, if ever warranted, is S8's job (measure first).

## Future Apply hardening (documented now, not implemented)

No Apply engine exists in S3 — this is planning guidance for whenever
one is built. `uv`'s official installer supports environment variables
(e.g. `INSTALLER_NO_MODIFY_PATH`) that skip its own shell-rc PATH
edits; a future Serein-controlled `uv` install should use them and let
a separate, explicit, user-visible step own any rc-file edit, for the
same reason system Python is never a mutation target: an installer's
side effects on a user's shell configuration should never be silent.
