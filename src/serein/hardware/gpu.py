"""GPU enumeration via ``/sys/class/drm``.

Each ``cardN`` DRM node exposes PCI vendor/device hex IDs at
``device/vendor`` and ``device/device``. We map the well-known vendor IDs
(Intel/AMD/NVIDIA) to a label and a naive integrated-vs-discrete guess
(Intel == integrated, AMD/NVIDIA == discrete). This is a documented
simplification: it does not know about Intel discrete Arc cards or AMD APUs.
Friendly model-name resolution (e.g. via a PCI ID database or ``lspci``
enrichment) is deferred to a later phase — S0 only guarantees the vendor
family and a stable, non-crashing shape.

``render*`` nodes are skipped: they alias a ``cardN`` we already counted.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import GPUDevice

_VENDOR_IDS = {
    "0x8086": ("Intel", "integrated"),
    "0x1002": ("AMD", "discrete"),
    "0x10de": ("NVIDIA", "discrete"),
}


def detect_gpus(root: Path) -> list[GPUDevice]:
    drm_dir = root / "sys" / "class" / "drm"
    if not drm_dir.is_dir():
        return []

    devices: list[GPUDevice] = []
    try:
        entries = sorted(p.name for p in drm_dir.iterdir())
    except OSError:
        return []

    for name in entries:
        if not name.startswith("card") or "-" in name:
            continue
        vendor_hex = read_text(drm_dir / name / "device" / "vendor")
        device_hex = read_text(drm_dir / name / "device" / "device")
        vendor_hex = vendor_hex.strip().lower() if vendor_hex else None
        label, kind = _VENDOR_IDS.get(vendor_hex or "", (vendor_hex, "unknown"))
        model = device_hex.strip() if device_hex else None
        devices.append(GPUDevice(vendor=label, model=model, kind=kind))

    return devices
