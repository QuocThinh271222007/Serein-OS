"""Serein OS Distribution subsystem (S7.0): bootable ISO prototype.

Assembles a private, internal "Serein Alpha" ISO by remastering a
verified upstream Ubuntu release image with a controlled Serein payload
overlay. See ``docs/distribution/architecture.md`` for the full design.

**No public release exists yet** - the project has no selected license
(see ``docs/distribution/licensing-and-release-boundary.md``). Every
artifact this subsystem produces is a private development alpha.
"""

from __future__ import annotations
