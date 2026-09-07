"""Serein media payload assembly (S7.0 Sections 23-27, 62-63).

The payload proves S0-S6.5's work can be embedded on distribution media -
it is never a full worktree copy (Section 24). Two independent pieces
make up the payload:

1. **Resource entries** - the declarative, non-Python resource trees
   (desktop assets, dev/hardware defaults, profile manifests, JSON
   schemas) hashed directly from the repository. This is what
   ``collect_resource_entries`` produces, and it is what Layer A tests
   exercise - no build tool required.
2. **The built wheel** - ``src/serein/**`` (which is where the AI, Cyber,
   Veil, and Focus subsystems keep their declarative manifests as Python
   modules) packaged via ``python -m build``. Building the wheel is a
   separate, explicit step (``build_wheel``) never invoked by the normal
   test suite - see Section 25 ("do not upload to PyPI"; this stays a
   private artifact regardless).

Embedding on media is never the same claim as "installed into a target
OS" (Section 55) - callers must not blur that distinction in status text.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from serein.distribution.models import PayloadEntry, PayloadManifest
from serein.distribution.pathsafety import PathSafetyError, resolve_within

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Top-level repository directories that may be embedded on media.
#: Nothing outside this allowlist is ever walked - see Section 69.
PAYLOAD_RESOURCE_ROOTS: tuple[str, ...] = (
    "desktop",
    "development",
    "hardware",
    "profiles",
    "schemas",
)

#: Directory names never walked into, anywhere under an allowlisted root
#: (Section 24) - developer caches, VCS metadata, virtualenvs, build
#: intermediates.
_EXCLUDED_DIR_NAMES = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", "node_modules", ".idea", ".vscode",
    "build", "dist", "cache",
})

#: File suffixes never embedded even inside an allowlisted root.
_EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".log"})


def collect_resource_entries(
    repo_root: Path = _REPO_ROOT,
    roots: Iterable[str] = PAYLOAD_RESOURCE_ROOTS,
) -> list[PayloadEntry]:
    """Hash every allowlisted, non-excluded file under ``roots``.

    Read-only, no network, no subprocess - safe to call from a unit
    test. Every path is validated with
    :func:`serein.distribution.pathsafety.resolve_within` before being
    read, so a symlink planted inside a resource root cannot smuggle a
    file from outside the repository into the payload manifest.
    """
    import hashlib

    entries: list[PayloadEntry] = []
    for root_name in roots:
        root_dir = repo_root / root_name
        if not root_dir.is_dir():
            continue
        for path in sorted(root_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part in _EXCLUDED_DIR_NAMES for part in path.relative_to(repo_root).parts):
                continue
            if path.suffix in _EXCLUDED_SUFFIXES:
                continue

            relative = path.relative_to(repo_root).as_posix()
            try:
                resolved = resolve_within(repo_root, relative)
            except PathSafetyError:
                continue  # a symlink escaped its root - never embedded
            if resolved != path.resolve():
                continue  # extra caution: resolved target must be the file itself

            digest = hashlib.sha256()
            digest.update(path.read_bytes())
            entries.append(
                PayloadEntry(
                    path=relative,
                    sha256=digest.hexdigest(),
                    size_bytes=path.stat().st_size,
                )
            )
    return entries


def build_payload_manifest(
    source_commit: str,
    repo_root: Path = _REPO_ROOT,
    roots: Iterable[str] = PAYLOAD_RESOURCE_ROOTS,
    extra_entries: Iterable[PayloadEntry] = (),
) -> PayloadManifest:
    """Assemble the full payload manifest: resource entries plus any
    ``extra_entries`` the caller already produced (e.g. a built wheel's
    :class:`PayloadEntry`, via :func:`build_wheel` + a caller-side hash)."""
    entries = collect_resource_entries(repo_root, roots)
    entries.extend(extra_entries)
    entries.sort(key=lambda e: e.path)
    return PayloadManifest(
        source_commit=source_commit,
        generated_from=tuple(roots),
        entries=tuple(entries),
    )


def build_wheel(repo_root: Path = _REPO_ROOT, out_dir: Path | None = None) -> Path:
    """Build the Serein Python wheel via ``python -m build --wheel``.

    Explicit, separate step - never invoked by ``pytest``/``ruff``/
    ``mypy``/``verify.sh`` (Section 12 applies to build tooling
    generally, not only the multi-GB ISO fetch). Requires the ``build``
    package to be installed; raises ``RuntimeError`` with the real
    subprocess output on failure rather than silently producing no
    wheel. Never uploads anywhere (Section 25 - the project is marked
    ``Private :: Do Not Upload``).
    """
    target_dir = out_dir or (repo_root / "build" / "work" / "wheel")
    target_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(target_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "wheel build failed (python -m build --wheel):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    wheels = sorted(target_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"python -m build reported success but no .whl found in {target_dir}")
    return wheels[-1]
