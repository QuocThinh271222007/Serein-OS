"""Serein OS S7.2 - First-boot provisioning.

Owns what happens *after* an S7.1-installed Serein base boots for the
first time: detect the S7.1 handoff, validate it, run a transactional,
idempotent, first-failure-wins provisioning sequence exactly once, and
mark completion durably. See ``docs/firstboot/architecture.md``.

This package never performs installation itself (that is S7.1's job,
``serein.installer``) and never implements recovery/rollback (that is a
future S7.3 concern) or runtime resource enforcement (a future S8
concern) - see ``docs/firstboot/known-limitations.md``.
"""

from __future__ import annotations
