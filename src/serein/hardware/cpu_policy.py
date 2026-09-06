"""CPU frequency-scaling policy detection via ``cpufreq`` sysfs.

Reads only ``cpu0``'s ``cpufreq`` directory as representative of the
system: heterogeneous per-core policies (e.g. Intel P/E cores running
different governors) exist but are out of scope for S2 — see
``docs/hardware/cpu-policy.md``. Absence of the directory (containers,
most VMs, WSL, or a kernel/CPU without cpufreq support at all) is a
normal, non-error state.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import CPUPolicyInfo

_CPUFREQ_REL = ("sys", "devices", "system", "cpu", "cpu0", "cpufreq")


def detect_cpu_policy(root: Path) -> CPUPolicyInfo:
    cpufreq_dir = root.joinpath(*_CPUFREQ_REL)
    if not cpufreq_dir.is_dir():
        return CPUPolicyInfo(cpufreq_present=False)

    driver = read_text(cpufreq_dir / "scaling_driver")
    governor = read_text(cpufreq_dir / "scaling_governor")
    available_governors = read_text(cpufreq_dir / "scaling_available_governors")
    epp_current = read_text(cpufreq_dir / "energy_performance_preference")
    epp_available = read_text(cpufreq_dir / "energy_performance_available_preferences")

    return CPUPolicyInfo(
        cpufreq_present=True,
        driver=driver.strip() if driver else None,
        governor=governor.strip() if governor else None,
        available_governors=available_governors.split() if available_governors else [],
        epp_current=epp_current.strip() if epp_current else None,
        epp_available=epp_available.split() if epp_available else [],
    )
