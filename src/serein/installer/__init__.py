"""Installer subsystem (S7.1) - guarded target-disk installation.

See ``docs/installer/architecture.md`` for the full design. In one
sentence: Serein integrates the existing Ubuntu 26.04 Subiquity/curtin
installer stack (never a custom partitioning engine - Section 4) behind
an explicit target-disk safety gate, so that ``NO EXPLICIT TARGET`` -> ``NO
DESTRUCTIVE INSTALL`` is enforced in code, not merely documented.
"""

from __future__ import annotations
