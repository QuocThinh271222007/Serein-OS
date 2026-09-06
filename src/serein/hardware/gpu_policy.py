"""GPU topology policy: confidence-scored hybrid-graphics and
compute-driver detection.

Builds on ``serein.hardware.gpu`` (vendor + PCI-class-based, structural
``kind`` per DRM node — see that module's docstring) but adds one more
heuristic signal, ``device/boot_vga``, that is deliberately *not* used
for the schema-locked ``GPUDevice.kind`` field: which device the
firmware recorded as driving the boot display. This is real signal for
disambiguating roles in a multi-GPU system, but is a heuristic, not
proof — a solo Intel/AMD discrete GPU with no sibling shows the exact
same ``boot_vga=1`` + VGA-class combination a solo integrated GPU would.
Every classification this module produces therefore carries an explicit
``confidence`` alongside it, and ``hybrid`` is a tri-state
(``True``/``False``/``None`` for "topology genuinely unresolved") rather
than a boolean computed from possibly-wrong certainty.

See docs/hardware/gpu-policy.md and docs/validation/s2r/gpu-corrective.md.
"""

from __future__ import annotations

from pathlib import Path

from serein.hardware._util import read_text
from serein.hardware.gpu import SUBCLASS_3D_ONLY, SUBCLASS_VGA, read_class_subclass
from serein.hardware.models import GPUClassification, GPUDevice, GPUPolicyInfo

_VENDOR_LABELS = {
    "0x8086": "Intel",
    "0x1002": "AMD",
    "0x10de": "NVIDIA",
}


def _read_boot_vga(device_dir: Path) -> bool | None:
    text = read_text(device_dir / "boot_vga")
    if text is None:
        return None
    stripped = text.strip()
    if stripped == "1":
        return True
    if stripped == "0":
        return False
    return None


def _classify_with_confidence(
    vendor_label: str | None, class_subclass: str | None, boot_vga: bool | None, total_gpus: int
) -> tuple[str, str]:
    if class_subclass == SUBCLASS_3D_ONLY:
        # Vendor-independent structural evidence: this device cannot
        # drive a display, so it is a render/compute-offload part.
        return "discrete", "high"
    if vendor_label == "NVIDIA":
        # Documented target-market assumption, not structural proof.
        return "discrete", "high"
    if (
        total_gpus > 1
        and class_subclass == SUBCLASS_VGA
        and boot_vga is True
        and vendor_label in ("Intel", "AMD")
    ):
        # Heuristic, only meaningful with a sibling GPU to be relative
        # to: the boot-display device in a multi-GPU system is
        # conventionally the integrated part. In a SOLO-GPU system this
        # signal is worthless (a lone discrete desktop GPU is boot_vga=1
        # and VGA-class too), so it is deliberately not applied when
        # total_gpus <= 1 - see module docstring and
        # docs/hardware/gpu-policy.md.
        return "integrated", "medium"
    return "unknown", "low"


def _classify_all_devices(root: Path) -> list[GPUClassification]:
    drm_dir = root / "sys" / "class" / "drm"
    if not drm_dir.is_dir():
        return []
    try:
        names = sorted(
            p.name for p in drm_dir.iterdir() if p.name.startswith("card") and "-" not in p.name
        )
    except OSError:
        return []

    total_gpus = len(names)
    results: list[GPUClassification] = []
    for name in names:
        device_dir = drm_dir / name / "device"
        vendor_hex = read_text(device_dir / "vendor")
        vendor_hex = vendor_hex.strip().lower() if vendor_hex else None
        vendor_label = _VENDOR_LABELS.get(vendor_hex or "")
        class_subclass = read_class_subclass(device_dir)
        boot_vga = _read_boot_vga(device_dir)
        kind, confidence = _classify_with_confidence(
            vendor_label, class_subclass, boot_vga, total_gpus
        )
        results.append(
            GPUClassification(vendor=vendor_label or vendor_hex, kind=kind, confidence=confidence)
        )
    return results


def _kernel_module_loaded(root: Path, module: str) -> bool:
    modules_text = read_text(root / "proc" / "modules")
    if modules_text:
        for line in modules_text.splitlines():
            fields = line.split()
            if fields and fields[0] == module:
                return True
    return (root / "sys" / "module" / module).is_dir()


def detect_gpu_policy(root: Path, gpus: list[GPUDevice]) -> GPUPolicyInfo:
    classifications = _classify_all_devices(root)
    confident_integrated = sum(1 for c in classifications if c.kind == "integrated")
    confident_discrete = sum(1 for c in classifications if c.kind == "discrete")
    unknown = sum(1 for c in classifications if c.kind == "unknown")
    total = len(classifications)

    hybrid: bool | None
    hybrid_confidence: str
    if confident_integrated > 0 and confident_discrete > 0:
        hybrid = True
        contributing = [c.confidence for c in classifications if c.kind != "unknown"]
        if unknown > 0:
            hybrid_confidence = "low"
        elif "medium" in contributing:
            hybrid_confidence = "medium"
        else:
            hybrid_confidence = "high"
    elif total <= 1:
        hybrid = False
        hybrid_confidence = "high"
    elif unknown > 0:
        # Multiple GPUs, but topology is not fully resolved - honest
        # "unknown", never a guessed True or False.
        hybrid = None
        hybrid_confidence = "low"
    else:
        # Multiple GPUs, all confidently classified, same kind (e.g.
        # dual-NVIDIA) - genuinely not hybrid.
        hybrid = False
        hybrid_confidence = "high"

    nvidia_present = any(g.vendor == "NVIDIA" for g in gpus)

    return GPUPolicyInfo(
        hybrid=hybrid,
        hybrid_confidence=hybrid_confidence,
        classifications=classifications,
        nvidia_present=nvidia_present,
        nvidia_kernel_module_loaded=_kernel_module_loaded(root, "nvidia"),
        amdgpu_kernel_module_loaded=_kernel_module_loaded(root, "amdgpu"),
        integrated_count=confident_integrated,
        discrete_count=confident_discrete,
    )
