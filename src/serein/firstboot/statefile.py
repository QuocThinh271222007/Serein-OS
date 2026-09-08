"""Loads/persists :class:`serein.firstboot.models.FirstbootState`
(Section 6-9, 27-28).

``FirstbootStateStore`` is the only writer of
``/var/lib/serein/firstboot/state.json`` - every write goes through
:func:`serein.firstboot.atomic.atomic_write_json`, so a crash mid-write
can never corrupt the previously-checkpointed state.
"""

from __future__ import annotations

import json
from pathlib import Path

from .atomic import atomic_write_json
from .models import STEP_IDS, FirstbootState, StepRecord


class FirstbootStateStore:
    def __init__(self, path: Path):
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def load(self) -> FirstbootState:
        """Load persisted state, or a fresh ``pending`` state if none
        exists yet. Never raises on a missing file - a missing state
        file simply means "first boot has not started"."""
        if not self._path.exists():
            return FirstbootState(steps=[StepRecord(id=step_id) for step_id in STEP_IDS])

        text = self._path.read_text(encoding="utf-8")
        data = json.loads(text)
        state = FirstbootState.from_dict(data)
        state.steps = _reconcile_steps(state.steps)
        return state

    def load_corrupt_safe(self) -> tuple[FirstbootState | None, str | None]:
        """Read-only variant for ``serein firstboot doctor`` (Section 32
        - "state corrupt"): never raises, returns ``(None, error)``
        instead of propagating a ``json.JSONDecodeError``/``OSError``."""
        if not self._path.exists():
            return None, None
        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            return FirstbootState.from_dict(data), None
        except (OSError, ValueError, KeyError) as exc:
            return None, f"state_corrupt: {exc}"

    def save(self, state: FirstbootState, *, now_iso: str | None = None) -> None:
        if now_iso is not None:
            state.updated_at = now_iso
        atomic_write_json(self._path, state.to_dict())


def _reconcile_steps(steps: list[StepRecord]) -> list[StepRecord]:
    """Section 8: a persisted state file always carries exactly
    ``STEP_IDS`` in order. If the step list ever changes between builds,
    an older on-disk state is reconciled rather than trusted blindly:
    known ids keep their recorded status; unknown/missing ids are never
    silently dropped or duplicated."""
    by_id = {s.id: s for s in steps}
    return [by_id.get(step_id, StepRecord(id=step_id)) for step_id in STEP_IDS]
