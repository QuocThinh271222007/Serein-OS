"""Read-only hardware discovery.

Every probe function accepts a ``root`` path that stands in for the
filesystem root (``/``). Production code calls with the default, real root;
tests pass a fixture directory tree instead, so parsing logic never depends
on the actual host. See ``docs/architecture/hardware-contract.md``.
"""

from serein.hardware.models import SCHEMA_VERSION, HardwareReport
from serein.hardware.probe import probe_hardware

__all__ = ["HardwareReport", "SCHEMA_VERSION", "probe_hardware"]
