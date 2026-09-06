"""GPU enumeration via ``/sys/class/drm``.

Each ``cardN`` DRM node exposes PCI vendor/device hex IDs at
``device/vendor``/``device/device``. Vendor alone is **not** sufficient
evidence for integrated-vs-discrete classification — AMD and Intel both
ship both kinds (APUs and discrete Arc/Radeon parts), so vendor-only
classification was a real S2 defect (see docs/hardware/gpu-policy.md and
docs/validation/s2r/gpu-corrective.md).

S2R correction: ``kind`` now uses only the one vendor-independent,
structurally-provable signal available without a PCI ID database — the
PCI class code at ``device/class`` (a stable PCI SIG convention). Subclass
``02`` ("3D controller") means the device cannot drive a display
directly: a real signal that it's a render/compute-offload part, almost
always the *discrete* GPU in a hybrid system, regardless of vendor.
Everything else vendor/class-wise is reported ``"unknown"`` here —
**except** NVIDIA, which remains classified ``"discrete"`` on vendor
alone as a documented target-market assumption (NVIDIA does not
currently ship integrated GPUs Serein would encounter on an Ubuntu
workstation).

This is deliberately more conservative than a full topology model: a
laptop's Intel/AMD integrated GPU (VGA-class, no distinguishing 3D-only
subclass) now reports ``"unknown"`` here rather than a guessed
``"integrated"``. The richer, confidence-scored classification used for
`serein hardware capabilities`/`plan` (which *does* also consider
``device/boot_vga`` as an additional heuristic signal) lives in
``serein.hardware.gpu_policy`` — a separate, S2-only structure, so this
schema-locked ``GPUDevice.kind`` field never has to represent a
confidence level it doesn't have room for.

``render*`` nodes are skipped: they alias a ``cardN`` we already counted.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.models import GPUDevice

_VENDOR_LABELS = {
    "0x8086": "Intel",
    "0x1002": "AMD",
    "0x10de": "NVIDIA",
}

#: PCI class code (class + subclass, the first 4 hex digits after "0x")
#: for "Display controller / 3D controller" - a device with no display
#: output, per the PCI SIG class code table.
SUBCLASS_3D_ONLY = "0302"
#: "Display controller / VGA compatible controller".
SUBCLASS_VGA = "0300"


def read_class_subclass(device_dir: Path) -> str | None:
    """Shared with gpu_policy.py so both modules agree on parsing, even
    though each applies its own classification confidence on top."""
    text = read_text(device_dir / "class")
    if not text:
        return None
    value = text.strip().lower().removeprefix("0x")
    return value[:4] if len(value) >= 4 else None


def classify_gpu_kind(vendor_label: str | None, class_subclass: str | None) -> str:
    """Returns "integrated" | "discrete" | "unknown" using only
    vendor-independent, structural evidence (plus the documented NVIDIA
    assumption). No boot_vga here - see module docstring for why."""
    if class_subclass == SUBCLASS_3D_ONLY:
        return "discrete"
    if vendor_label == "NVIDIA":
        return "discrete"
    return "unknown"


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
        device_dir = drm_dir / name / "device"
        vendor_hex = read_text(device_dir / "vendor")
        device_hex = read_text(device_dir / "device")
        vendor_hex = vendor_hex.strip().lower() if vendor_hex else None
        vendor_label = _VENDOR_LABELS.get(vendor_hex or "")
        model = device_hex.strip() if device_hex else None

        class_subclass = read_class_subclass(device_dir)
        kind = classify_gpu_kind(vendor_label, class_subclass)

        devices.append(GPUDevice(vendor=vendor_label or vendor_hex, model=model, kind=kind))

    return devices
