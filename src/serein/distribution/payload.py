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
   modules) packaged via ``python -m build --no-isolation`` (fast,
   network-free - Section 12's "no silent network download" principle
   applied to build tooling generally). As of S7.0R,
   ``serein.distribution.build.run_build`` calls :func:`build_wheel` and
   :func:`inspect_wheel_contents` as part of the canonical pipeline, and
   embeds the result via :func:`wheel_artifact` - it is real media
   assembly, not merely a helper function available somewhere. Never
   uploaded anywhere - see Section 25 ("do not upload to PyPI"; this
   stays a private artifact regardless).

Embedding on media is never the same claim as "installed into a target
OS" (Section 55) - callers must not blur that distinction in status text.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from serein.distribution.models import PayloadEntry, PayloadManifest
from serein.distribution.pathsafety import PathSafetyError, resolve_within

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Payload-relative directory the built wheel is embedded under
#: (Section 24 of the S7.0R corrective) - "packages/<wheel filename>".
WHEEL_PAYLOAD_SUBDIR = "packages"

#: Representative module paths every Serein control-plane wheel must
#: contain (Section 23) - not exhaustive, just enough to prove the CLI
#: core and every completed phase's package made it into the wheel.
EXPECTED_WHEEL_MODULES: tuple[str, ...] = (
    "serein/__init__.py",
    "serein/cli.py",
    "serein/ai/__init__.py",
    "serein/cyber/__init__.py",
    "serein/veil/__init__.py",
    "serein/focus/__init__.py",
    "serein/distribution/__init__.py",
)


@dataclass(frozen=True)
class PayloadArtifact:
    """A payload entry paired with where its real bytes actually live
    on the build host right now (Section 25).

    ``source_path`` is intentionally never part of
    :class:`~serein.distribution.models.PayloadEntry`/
    ``PayloadManifest`` - it is a build-time-only field the copy step
    consumes, and it is never serialized into any manifest or media
    marker (no build-host absolute path ever leaks into the public
    payload contract).
    """

    entry: PayloadEntry
    source_path: Path


class WheelContentError(ValueError):
    """Raised when a built wheel is missing an expected Serein
    control-plane module - fail closed rather than embed a wheel that
    silently doesn't contain what it claims to."""

#: Top-level repository directories that may be embedded on media.
#: Nothing outside this allowlist is ever walked - see Section 69.
PAYLOAD_RESOURCE_ROOTS: tuple[str, ...] = (
    "branding",
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


def collect_resource_artifacts(
    repo_root: Path = _REPO_ROOT,
    roots: Iterable[str] = PAYLOAD_RESOURCE_ROOTS,
) -> list[PayloadArtifact]:
    """Same walk as :func:`collect_resource_entries`, but pairs each
    entry with its real source path so the copy step never has to
    assume "everything lives under ``repo_root``" (that assumption is
    only true for resource entries, not for a built wheel -
    Section 25)."""
    return [
        PayloadArtifact(entry=entry, source_path=repo_root / entry.path)
        for entry in collect_resource_entries(repo_root, roots)
    ]


def wheel_artifact(wheel_path: Path, payload_subdir: str = WHEEL_PAYLOAD_SUBDIR) -> PayloadArtifact:
    """Build the :class:`PayloadArtifact` for an already-built wheel
    file. The payload-relative path is deterministic
    (``packages/<filename>``, Section 24) and never encodes the
    build-host's absolute path - only ``source_path`` (build-time-only,
    never serialized) points at the real file."""
    import hashlib

    data = wheel_path.read_bytes()
    entry = PayloadEntry(
        path=f"{payload_subdir}/{wheel_path.name}",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    return PayloadArtifact(entry=entry, source_path=wheel_path)


def inspect_wheel_contents(
    wheel_path: Path, expected_modules: Iterable[str] = EXPECTED_WHEEL_MODULES
) -> None:
    """Verify a built wheel actually contains the expected Serein
    control-plane modules (Section 23) before it is embedded - reads
    the wheel's own zip index, never installs it anywhere. Raises
    :class:`WheelContentError` listing exactly what is missing."""
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())

    missing = [module for module in expected_modules if module not in names]
    if missing:
        raise WheelContentError(
            f"built wheel {wheel_path.name} is missing expected modules: {missing}"
        )


def build_payload_manifest(
    source_commit: str,
    repo_root: Path = _REPO_ROOT,
    roots: Iterable[str] = PAYLOAD_RESOURCE_ROOTS,
    extra_entries: Iterable[PayloadEntry] = (),
) -> PayloadManifest:
    """Assemble the full payload manifest: resource entries plus any
    ``extra_entries`` the caller already produced (e.g. a built wheel's
    :class:`PayloadEntry`, via :func:`wheel_artifact`)."""
    entries = collect_resource_entries(repo_root, roots)
    entries.extend(extra_entries)
    entries.sort(key=lambda e: e.path)
    return PayloadManifest(
        source_commit=source_commit,
        generated_from=tuple(roots),
        entries=tuple(entries),
    )


def build_wheel(
    repo_root: Path = _REPO_ROOT,
    out_dir: Path | None = None,
    subprocess_runner: object = subprocess.run,
    no_isolation: bool = True,
) -> Path:
    """Build the Serein Python wheel via ``python -m build --wheel``.

    Part of the canonical media-assembly pipeline as of S7.0R
    (``serein.distribution.build.run_build`` calls this by default) -
    never invoked by ``pytest``/``ruff``/``mypy``/``verify.sh``
    themselves, since none of those import ``build.run_build`` with its
    default wheel-building behavior active without a caller opting in.
    ``no_isolation=True`` (the default) builds against this
    interpreter's already-installed ``setuptools``/``wheel`` rather than
    spinning up an isolated build environment that would need a PyPI
    fetch - keeping this fast and network-independent, consistent with
    Section 12's "no silent network download" principle extended to
    build tooling generally. ``subprocess_runner`` is injectable so a
    caller (or a test) can fake this without invoking a real
    subprocess. Never uploads anywhere (Section 25 - the project is
    marked ``Private :: Do Not Upload``).
    """
    target_dir = out_dir or (repo_root / "build" / "work" / "wheel")
    target_dir.mkdir(parents=True, exist_ok=True)

    command = [sys.executable, "-m", "build", "--wheel", "--outdir", str(target_dir)]
    if no_isolation:
        command.append("--no-isolation")

    result = subprocess_runner(  # type: ignore[operator]
        command, cwd=repo_root, capture_output=True, text=True, check=False
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
