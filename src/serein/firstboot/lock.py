"""Concurrency control for first-boot provisioning (Section 28 -
"Prevent two provisioning processes from running simultaneously").

On POSIX, uses a PID file plus ``fcntl.flock`` in non-blocking exclusive
mode - the kernel releases an ``flock`` automatically when the holding
process exits or crashes, so a crashed provisioning run can never leave
a permanently stuck lock behind (unlike a bare "lockfile exists" check).

**Documented platform limitation**: this repository's own dev/CI
environment is Windows, which has no ``fcntl``. When unavailable, the
lock degrades to an exclusive-create (``open(path, "x")``) best-effort
mutual-exclusion primitive: it correctly blocks a second concurrent
``acquire()`` from a live process, but - unlike real ``flock`` - it is
*not* automatically released if the holding process crashes without
calling ``release()``, so a stale lock file from a crashed process could
require manual/administrative cleanup. Serein's real target platform is
Ubuntu/systemd, where the ``fcntl`` path is always used; the degraded
path exists only so this module is exercised and tested on this
Windows development host, never as the production mechanism.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import TextIO

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - exercised on Windows dev/CI
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False


class FirstbootLock:
    """A single, process-exclusive lock guarding one provisioning run.
    Use as a context manager, or call :meth:`acquire`/:meth:`release`
    directly (``run_firstboot`` needs the boolean return of a failed
    ``acquire`` to report ``LOCKED`` rather than raising)."""

    def __init__(self, lock_path: Path):
        self._lock_path = lock_path
        #: An open file handle while holding the real ``fcntl`` lock, the
        #: lock path itself as a "held, degraded mode" sentinel, or None.
        self._fh: TextIO | Path | None = None

    @property
    def using_real_flock(self) -> bool:
        """True when this platform's kernel-enforced, crash-safe lock is
        in use; False when running under the degraded fallback."""
        return _HAS_FCNTL

    def acquire(self) -> bool:
        if self._fh is not None:
            return True  # already held by this instance

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        if _HAS_FCNTL:
            handle = open(self._lock_path, "a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[union-attr]
            except OSError:
                handle.close()
                return False
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
            self._fh = handle
            return True

        # Degraded fallback (documented above) - exclusive create.
        try:
            fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        self._fh = self._lock_path  # sentinel: "held, degraded mode"
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        if _HAS_FCNTL and not isinstance(self._fh, Path):
            handle = self._fh
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()
        else:
            try:
                self._lock_path.unlink()
            except OSError:
                pass
        self._fh = None

    def __enter__(self) -> FirstbootLock:
        if not self.acquire():
            raise LockHeldError(f"lock already held: {self._lock_path}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class LockHeldError(RuntimeError):
    """Raised only by the context-manager form; ``run_firstboot`` itself
    uses the boolean :meth:`FirstbootLock.acquire` return instead, so it
    can report a clean ``LOCKED`` status rather than propagating an
    exception."""


def is_lock_held(lock_path: Path) -> bool:
    """Read-only diagnostic probe for ``serein firstboot doctor``
    (Section 32 - "lock held"). Never mutates persisted state: on the
    real ``fcntl`` path it takes the lock non-blocking and immediately
    releases it again if successful (the standard "is this currently
    locked" idiom - equivalent to ``flock -n lockfile -c true``), so a
    successful probe leaves the lock exactly as it found it. On the
    degraded fallback, held is simply "the lock file exists" (which is
    already both necessary and sufficient there, since the degraded path
    has no independent liveness check)."""
    if not lock_path.exists():
        return False

    if not _HAS_FCNTL:
        return True

    try:
        handle = open(lock_path, "a+", encoding="utf-8")
    except OSError:
        return False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[union-attr]
    except OSError:
        return True
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[union-attr]
        return False
    finally:
        handle.close()
