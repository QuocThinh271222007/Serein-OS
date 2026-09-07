"""Serein control-plane CLI entry point.

Built on ``argparse`` only — see ``docs/adr/0003-control-plane-language.md``
for why S0 avoids a CLI framework dependency. Every command here is
read-only: S0 defines the installer/mutation contract in
``docs/architecture/installer-contract.md`` but implements no mutation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from serein import __version__
from serein.ai.capabilities import build_ai_capabilities
from serein.ai.doctor import run_ai_checks
from serein.ai.planner import VALID_COMPONENTS as AI_VALID_COMPONENTS
from serein.ai.planner import build_ai_plan
from serein.ai.status import build_ai_status
from serein.core.status import build_status_report
from serein.cyber.capabilities import build_cyber_capabilities
from serein.cyber.doctor import run_cyber_checks
from serein.cyber.planner import VALID_COMPONENTS as CYBER_VALID_COMPONENTS
from serein.cyber.planner import build_cyber_plan
from serein.cyber.status import build_cyber_status
from serein.desktop.config import RESOURCES, missing_resources
from serein.desktop.doctor import run_desktop_checks
from serein.desktop.plan import build_desktop_plan
from serein.desktop.status import build_desktop_status
from serein.development.capabilities import build_development_capabilities
from serein.development.doctor import run_development_checks
from serein.development.models import ToolStatus
from serein.development.planner import VALID_COMPONENTS as DEV_VALID_COMPONENTS
from serein.development.planner import build_development_plan
from serein.development.status import build_development_status
from serein.doctor.checks import run_checks
from serein.doctor.models import CheckStatus, DoctorReport
from serein.hardware._util import DEFAULT_ROOT
from serein.hardware.capabilities import build_capabilities
from serein.hardware.cpu_policy import detect_cpu_policy
from serein.hardware.doctor import run_hardware_checks
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.hardware.memory_policy import detect_memory_policy
from serein.hardware.planner import VALID_PROFILES, build_hardware_plan
from serein.hardware.power_policy import detect_power_policy
from serein.hardware.probe import probe_hardware
from serein.hardware.storage_policy import detect_storage_policy
from serein.hardware.thermal import detect_thermal
from serein.profiles.registry import list_profiles
from serein.veil.capabilities import build_veil_capabilities
from serein.veil.doctor import run_veil_checks
from serein.veil.planner import VALID_COMPONENTS as VEIL_VALID_COMPONENTS
from serein.veil.planner import build_veil_plan
from serein.veil.status import build_veil_status

_CAPABILITY_LABELS = {
    "cpu_governor_control": "CPU governor control",
    "cpu_epp_control": "CPU EPP control",
    "zram_configurable": "ZRAM configurable",
    "swap_exists": "Swap exists",
    "storage_scheduler_configurable": "Storage scheduler configurable",
    "battery_detected": "Battery detected",
    "power_profile_control": "Power profile control",
    "nvidia_compute_gpu": "NVIDIA compute GPU",
    "gpu_switching": "GPU switching",
    "thermal_telemetry": "Thermal telemetry",
}

_DEV_CAPABILITY_LABELS = {
    "git_cli": "Git",
    "github_cli": "GitHub CLI",
    "python_uv": "Python (uv)",
    "node_runtime": "Node runtime (fnm)",
    "pnpm": "pnpm",
    "rustup": "Rust (rustup)",
    "go_toolchain": "Go toolchain",
    "cpp_toolchain": "C/C++ toolchain",
    "zed_editor": "Zed editor",
    "container_engine": "Container engine",
    "distrobox": "Distrobox",
}

_AI_CAPABILITY_LABELS = {
    "nvidia_hardware": "NVIDIA hardware",
    "nvidia_driver": "NVIDIA driver",
    "cuda_runtime": "CUDA driver runtime",
    "cuda_toolkit": "CUDA Toolkit",
    "rocm_runtime": "ROCm runtime",
    "intel_gpu_runtime": "Intel GPU runtime",
    "pytorch": "PyTorch",
    "pytorch_cuda": "PyTorch (CUDA)",
    "pytorch_rocm": "PyTorch (ROCm)",
    "pytorch_cpu": "PyTorch (CPU)",
    "ollama": "Ollama",
    "llama_cpp": "llama.cpp",
    "vllm": "vLLM",
    "onnxruntime": "ONNX Runtime",
    "tensorrt": "TensorRT",
    "ai_container_runtime": "AI container runtime",
}

_CYBER_CAPABILITY_LABELS = {
    "network_diagnostics": "Network diagnostics",
    "packet_capture_tools": "Packet capture tools",
    "packet_capture_permission": "Capture permission",
    "dns_diagnostics": "DNS diagnostics",
    "tls_diagnostics": "TLS diagnostics",
    "network_scanning_tools": "Network scanning tools",
    "web_testing_toolbox": "Web testing toolbox",
    "reverse_engineering": "Reverse engineering",
    "forensics_toolbox": "Forensics toolbox",
    "wireless_tooling": "Wireless tooling",
    "container_toolbox": "Container toolbox",
    "vm_isolation": "VM isolation",
}

_VEIL_CAPABILITY_LABELS = {
    "tor_client": "Tor client",
    "tor_socks": "torsocks",
    "tor_browser": "Tor Browser",
    "private_browser_profile": "Private browser profile",
    "dns_isolation": "DNS isolation",
    "tor_only_routing": "Tor-only routing",
    "kill_switch": "Kill switch",
    "private_workspace": "Private workspace",
    "whonix_vm": "Whonix VM",
    "vm_privacy_boundary": "VM privacy boundary",
}


def _yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _format_bytes(n: int | None) -> str:
    if n is None:
        return "unavailable"
    gib = n / (1024**3)
    return f"{gib:.1f} GiB"


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    status = build_status_report()
    print("SEREIN")
    print(f"Version:              {status.version}")
    print(f"Host compatibility:   {status.os_compatibility}")
    print(f"Kernel release:       {status.kernel_release or 'unavailable'}")
    print(f"Architecture:         {status.architecture or 'unavailable'}")
    cpu = f"{status.cpu_vendor or 'unknown vendor'} {status.cpu_model or ''}".strip()
    print(f"CPU:                  {cpu or 'unavailable'}")
    print(f"Logical CPUs:         {status.logical_cpus if status.logical_cpus else 'unavailable'}")
    print(f"RAM:                  {_format_bytes(status.memory_total_bytes)}")
    print(f"GPU:                  {', '.join(status.gpu_summary)}")
    print(f"Virtualization:       {status.virtualization}")
    print(f"Current profile:      {status.current_profile}")
    return 0


def _print_doctor_report(header: str, report: DoctorReport) -> None:
    print(header)
    for check in report.checks:
        marker = {
            CheckStatus.PASS: "PASS",
            CheckStatus.WARN: "WARN",
            CheckStatus.FAIL: "FAIL",
            CheckStatus.SKIP: "SKIP",
        }[check.status]
        print(f"[{marker:4}] {check.title}: {check.detail}")

    summary = report.summary
    print(
        "Summary: "
        f"{summary['PASS']} pass, {summary['WARN']} warn, "
        f"{summary['FAIL']} fail, {summary['SKIP']} skip"
    )


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = run_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN DOCTOR", report)
    return report.exit_code


def _cmd_hardware_probe(args: argparse.Namespace) -> int:
    report = probe_hardware()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN HARDWARE PROBE")
    print(f"OS:              {report.os.pretty_name or 'unavailable'}")
    print(f"Kernel:          {report.kernel.release or 'unavailable'}")
    print(f"Architecture:    {report.cpu.architecture or 'unavailable'}")
    cpu = f"{report.cpu.vendor or 'unknown vendor'} {report.cpu.model_name or ''}".strip()
    print(f"CPU:             {cpu or 'unavailable'}")
    print(
        "Cores:           "
        f"{report.cpu.physical_cores or '?'} physical / {report.cpu.logical_cores or '?'} logical"
    )
    print(f"Memory total:    {_format_bytes(report.memory.total_bytes)}")
    if report.gpu:
        for gpu in report.gpu:
            print(f"GPU:             {gpu.vendor or 'unknown'} ({gpu.kind or 'unknown'})")
    else:
        print("GPU:             unavailable")
    if report.storage:
        for device in report.storage:
            print(
                f"Storage:         {device.name} [{device.device_class}] "
                f"{_format_bytes(device.size_bytes)}"
            )
    else:
        print("Storage:         unavailable")
    print(f"Battery:         {'present' if report.power.has_battery else 'not present'}")
    print(f"Virtualization:  {report.environment.virtualization}")
    return 0


def _cmd_hardware_status(_args: argparse.Namespace) -> int:
    hw = probe_hardware()
    cpu_policy = detect_cpu_policy(DEFAULT_ROOT)
    memory_policy = detect_memory_policy(DEFAULT_ROOT)
    storage_policy = detect_storage_policy(DEFAULT_ROOT)
    power_policy = detect_power_policy(DEFAULT_ROOT)
    gpu_policy = detect_gpu_policy(DEFAULT_ROOT, hw.gpu)
    thermal = detect_thermal(DEFAULT_ROOT)

    print("SEREIN HARDWARE")
    print()
    print("CPU")
    cpu_label = f"{hw.cpu.vendor or 'unknown vendor'} {hw.cpu.model_name or ''}".strip()
    print(f"  {cpu_label or 'unavailable'}")
    print(f"  Driver        {cpu_policy.driver or 'not detected'}")
    print(f"  Governor      {cpu_policy.governor or 'not detected'}")
    print(f"  EPP           {cpu_policy.epp_current or 'not available'}")
    print()
    print("Memory")
    print(f"  RAM           {_format_bytes(hw.memory.total_bytes)}")
    disk_swap = [s for s in memory_policy.swap_devices if s.kind != "zram"]
    if disk_swap:
        total = sum(s.size_bytes or 0 for s in disk_swap)
        print(f"  Swap          {_format_bytes(total)} ({len(disk_swap)} device(s))")
    else:
        print("  Swap          none")
    if memory_policy.zram_devices:
        zram = memory_policy.zram_devices[0]
        algo = zram.comp_algorithm or "unknown algorithm"
        print(f"  ZRAM          {_format_bytes(zram.disksize_bytes)} ({algo})")
    else:
        print("  ZRAM          not configured")
    print()
    print("Storage")
    if storage_policy.devices:
        for device in storage_policy.devices:
            print(f"  {device.name:<12}  scheduler={device.current_scheduler or 'unknown'}")
    else:
        print("  unavailable")
    print()
    print("Power")
    print(f"  Device        {'laptop' if hw.power.has_battery else 'desktop'}")
    if hw.power.on_ac_power is True:
        ac = "connected"
    elif hw.power.on_ac_power is False:
        ac = "not connected"
    else:
        ac = "unknown"
    print(f"  AC            {ac}")
    if power_policy.batteries:
        for battery in power_policy.batteries:
            if battery.capacity_percent is not None:
                pct = f"{battery.capacity_percent}%"
            else:
                pct = "unknown"
            print(f"  Battery       {pct} ({battery.status or 'unknown status'})")
    else:
        print("  Battery       not present")
    print()
    print("GPU")
    if hw.gpu:
        for gpu in hw.gpu:
            print(f"  {gpu.vendor or 'unknown'} ({gpu.kind or 'unknown'})")
    else:
        print("  unavailable")
    print(f"  Hybrid        {_yes_no_unknown(gpu_policy.hybrid)}")
    print()
    print("Thermal")
    telemetry = "available" if (thermal.zones or thermal.hwmon_present) else "not available"
    print(f"  sensors       {telemetry}")
    return 0


def _cmd_hardware_doctor(args: argparse.Namespace) -> int:
    report = run_hardware_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN HARDWARE DOCTOR", report)
    return report.exit_code


def _cmd_hardware_capabilities(args: argparse.Namespace) -> int:
    report = build_capabilities()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN HARDWARE CAPABILITIES")
    print()
    for capability in report.capabilities:
        label = _CAPABILITY_LABELS.get(capability.id, capability.id)
        print(f"{label:<32}{_yes_no_unknown(capability.available)}")
    return 0


def _cmd_hardware_plan(args: argparse.Namespace) -> int:
    plan = build_hardware_plan(args.profile)
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    print(f"SEREIN HARDWARE PLAN - {plan.profile_id}")
    print()
    if not plan.profile_available:
        print(f"Profile available: no ({plan.unavailable_reason})")
        return 0
    print("Profile available: yes")
    print()
    print("Actions:")
    for step in plan.actions:
        target = f" -> {step.target}" if step.target else ""
        current = f" (current: {step.current})" if step.current else ""
        print(f"  [{step.status:<7}] {step.component}.{step.action}{target}{current}")
        print(f"            reason: {step.reason}")
        print(
            f"            risk: {step.risk} | reversible: {'yes' if step.reversible else 'no'} | "
            f"requires_root: {'yes' if step.requires_root else 'no'}"
        )
        print(f"            verify: {step.verification}")
    return 0


def _tool_line(label: str, status: ToolStatus) -> str:
    value = status.version if status.installed else "missing"
    return f"  {label:<14} {value}"


def _cmd_dev_status(_args: argparse.Namespace) -> int:
    status = build_development_status()
    print("SEREIN DEVELOPMENT")
    print()
    print(f"Profile        {status.profile_id} ({status.profile_status})")
    print()
    print("Git")
    print(_tool_line("git", status.git.git))
    print(_tool_line("git-lfs", status.git.git_lfs))
    print(_tool_line("gh", status.git.gh))
    print()
    print("Editor")
    print(_tool_line("Zed", status.editor.zed))
    print()
    print("Python")
    print(_tool_line("system", status.python.system_python))
    print(_tool_line("uv", status.python.uv))
    print(f"  pyenv present  {'yes' if status.python.pyenv_present else 'no'}")
    print(f"  conda present  {'yes' if status.python.conda_present else 'no'}")
    print()
    print("Node")
    print(_tool_line("fnm", status.node.fnm))
    print(_tool_line("mise", status.node.mise))
    print(f"  nvm present    {'yes' if status.node.nvm_present else 'no'}")
    print(_tool_line("node", status.node.node))
    print(_tool_line("pnpm", status.node.pnpm))
    print(_tool_line("npm", status.node.npm))
    print()
    print("Rust")
    print(_tool_line("rustup", status.rust.rustup))
    print(_tool_line("rustc", status.rust.rustc))
    print(_tool_line("cargo", status.rust.cargo))
    print()
    print("Go")
    print(_tool_line("go", status.go.go))
    print()
    print("C/C++")
    print(_tool_line("gcc", status.cpp.gcc))
    print(_tool_line("g++", status.cpp.gpp))
    print(_tool_line("clang", status.cpp.clang))
    print(_tool_line("cmake", status.cpp.cmake))
    print(_tool_line("ninja", status.cpp.ninja))
    print(_tool_line("gdb", status.cpp.gdb))
    print(_tool_line("lldb", status.cpp.lldb))
    print()
    print("Containers")
    print(_tool_line("podman", status.containers.podman))
    print(_tool_line("docker", status.containers.docker))
    print(_tool_line("distrobox", status.containers.distrobox))
    return 0


def _cmd_dev_doctor(args: argparse.Namespace) -> int:
    report = run_development_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN DEVELOPMENT DOCTOR", report)
    return report.exit_code


def _cmd_dev_capabilities(args: argparse.Namespace) -> int:
    report = build_development_capabilities()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN DEVELOPMENT CAPABILITIES")
    print()
    for capability in report.capabilities:
        label = _DEV_CAPABILITY_LABELS.get(capability.id, capability.id)
        print(f"{label:<24}{_yes_no_unknown(capability.available)}")
    return 0


def _cmd_dev_plan(args: argparse.Namespace) -> int:
    plan = build_development_plan(getattr(args, "component", None))
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    header = "SEREIN DEVELOPMENT PLAN"
    if getattr(args, "component", None):
        header += f" - {args.component}"
    print(header)
    print()
    for step in plan.actions:
        target = f" -> {step.target}" if step.target else ""
        current = f" (current: {step.current})" if step.current else ""
        print(f"  [{step.status:<7}] {step.component}.{step.action}: {step.tool}{target}{current}")
        print(f"            reason: {step.reason}")
        print(
            f"            risk: {step.risk} | reversible: {'yes' if step.reversible else 'no'} | "
            f"requires_root: {'yes' if step.requires_root else 'no'} | source: {step.source}"
        )
        print(f"            verify: {step.verification}")
    return 0


def _cmd_ai_status(_args: argparse.Namespace) -> int:
    status = build_ai_status()
    print("SEREIN AI")
    print()
    print(f"Profile        {status.profile_id} ({status.profile_status})")
    print()
    print("Backend")
    backend_conf = status.backend.primary_confidence
    print(f"  primary        {status.backend.primary} (confidence: {backend_conf})")
    print(f"  hybrid         {_yes_no_unknown(status.backend.hybrid)}")
    print()
    print("NVIDIA")
    print(f"  hardware       {'yes' if status.nvidia.hardware_present else 'no'}")
    print(_tool_line("nvidia-smi", status.nvidia.nvidia_smi))
    print(f"  driver         {status.nvidia.driver_version or 'missing'}")
    print(f"  CUDA (driver)  {status.nvidia.cuda_driver_api_version or 'unknown'}")
    print(f"  CUDA Toolkit   {'yes' if status.nvidia.cuda_toolkit_installed else 'no'}")
    print(_tool_line("nvidia-ctk", status.nvidia.nvidia_ctk))
    print()
    print("AMD")
    print(f"  hardware       {'yes' if status.amd.hardware_present else 'no'}")
    print(_tool_line("rocminfo", status.amd.rocminfo))
    print(f"  GPU enumerated {_yes_no_unknown(status.amd.rocm_support.gpu_enumerated)}")
    print()
    print("Intel")
    print(f"  hardware       {'yes' if status.intel.hardware_present else 'no'}")
    print(f"  kind           {status.intel.kind or 'n/a'}")
    print()
    print("PyTorch")
    print(_tool_line("torch", status.pytorch.installed))
    print(f"  backend        {status.pytorch.build_backend or 'n/a'}")
    decision = status.pytorch_decision
    print(f"  plan target    {decision.target} ({decision.status.lower()})")
    print(f"  plan reason    {decision.reason}")
    print()
    print("Python AI packages")
    print(_tool_line("transformers", status.python_packages.transformers))
    print(_tool_line("accelerate", status.python_packages.accelerate))
    print(_tool_line("safetensors", status.python_packages.safetensors))
    print(_tool_line("huggingface_hub", status.python_packages.huggingface_hub))
    print()
    print("Inference")
    print(_tool_line("ollama", status.inference.ollama.binary))
    print(f"  service active {_yes_no_unknown(status.inference.ollama.service_active)}")
    print(_tool_line("llama-cli", status.inference.llama_cpp.llama_cli))
    print(_tool_line("llama-server", status.inference.llama_cpp.llama_server))
    print()
    print("Containers")
    print(_tool_line("podman", status.containers.podman))
    print(_tool_line("docker", status.containers.docker))
    print(_tool_line("nvidia-ctk", status.containers.nvidia_container_toolkit))
    print()
    print("Storage")
    print(f"  HF cache       {status.storage.hf_home}")
    print(f"  Ollama models  {status.storage.ollama_models}")
    return 0


def _cmd_ai_doctor(args: argparse.Namespace) -> int:
    report = run_ai_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN AI DOCTOR", report)
    return report.exit_code


def _cmd_ai_capabilities(args: argparse.Namespace) -> int:
    report = build_ai_capabilities()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN AI CAPABILITIES")
    print()
    for capability in report.capabilities:
        label = _AI_CAPABILITY_LABELS.get(capability.id, capability.id)
        usable = _yes_no_unknown(capability.usable)
        print(f"{label:<24}available={_yes_no_unknown(capability.available):<9}usable={usable}")
    return 0


def _cmd_ai_plan(args: argparse.Namespace) -> int:
    plan = build_ai_plan(getattr(args, "component", None))
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    header = "SEREIN AI PLAN"
    if getattr(args, "component", None):
        header += f" - {args.component}"
    print(header)
    print()
    for step in plan.actions:
        target = f" -> {step.target}" if step.target else ""
        current = f" (current: {step.current})" if step.current else ""
        print(f"  [{step.status:<7}] {step.component}.{step.action}: {step.tool}{target}{current}")
        print(f"            reason: {step.reason}")
        print(
            f"            risk: {step.risk} | reversible: {'yes' if step.reversible else 'no'} | "
            f"requires_root: {'yes' if step.requires_root else 'no'} | source: {step.source}"
        )
        print(f"            verify: {step.verification}")
    return 0


def _cmd_cyber_status(_args: argparse.Namespace) -> int:
    status = build_cyber_status()
    print("SEREIN CYBER")
    print()
    print(f"Profile        {status.profile_id} ({status.profile_status})")
    print()
    print("Network diagnostics")
    print(_tool_line("nmap", status.network.nmap))
    print(_tool_line("tcpdump", status.network.tcpdump))
    print(_tool_line("dig", status.network.dig))
    print(_tool_line("whois", status.network.whois))
    print(_tool_line("socat", status.network.socat))
    print(_tool_line("netcat", status.network.netcat))
    print(_tool_line("mtr", status.network.mtr))
    print(_tool_line("ethtool", status.network.ethtool))
    print(_tool_line("openssl", status.network.openssl))
    print()
    print("Packet capture")
    print(_tool_line("wireshark", status.capture.wireshark))
    print(_tool_line("tshark", status.capture.tshark))
    print(_tool_line("dumpcap", status.capture.dumpcap))
    print(f"  capture permitted {_yes_no_unknown(status.capture.capture_permitted)}")
    print()
    print("Reverse engineering")
    print(_tool_line("file", status.reverse.file))
    print(_tool_line("binutils", status.reverse.binutils))
    print(_tool_line("gdb", status.reverse.gdb))
    print(_tool_line("strace", status.reverse.strace))
    print(_tool_line("radare2", status.reverse.radare2))
    print(_tool_line("ghidra", status.reverse.ghidra))
    print()
    print("Isolation")
    print(_tool_line("podman", status.containers.podman))
    print(_tool_line("docker", status.containers.docker))
    print(_tool_line("distrobox", status.containers.distrobox))
    print(f"  KVM device     {'yes' if status.vm.kvm_device_present else 'no'}")
    print(f"  KVM module     {'yes' if status.vm.kvm_module_loaded else 'no'}")
    print(_tool_line("qemu", status.vm.qemu))
    print(_tool_line("virsh", status.vm.libvirt))
    print(f"  KVM access     {_yes_no_unknown(status.vm.user_access)}")
    return 0


def _cmd_cyber_doctor(args: argparse.Namespace) -> int:
    report = run_cyber_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN CYBER DOCTOR", report)
    return report.exit_code


def _cmd_cyber_capabilities(args: argparse.Namespace) -> int:
    report = build_cyber_capabilities()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN CYBER CAPABILITIES")
    print()
    for capability in report.capabilities:
        label = _CYBER_CAPABILITY_LABELS.get(capability.id, capability.id)
        usable = _yes_no_unknown(capability.usable)
        print(f"{label:<24}available={_yes_no_unknown(capability.available):<9}usable={usable}")
    return 0


def _cmd_cyber_plan(args: argparse.Namespace) -> int:
    plan = build_cyber_plan(getattr(args, "component", None))
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    header = "SEREIN CYBER PLAN"
    if getattr(args, "component", None):
        header += f" - {args.component}"
    print(header)
    print()
    for step in plan.actions:
        target = f" -> {step.target}" if step.target else ""
        current = f" (current: {step.current})" if step.current else ""
        print(f"  [{step.status:<7}] {step.component}.{step.action}: {step.tool}{target}{current}")
        print(f"            reason: {step.reason}")
        print(
            f"            risk: {step.risk} | reversible: {'yes' if step.reversible else 'no'} | "
            f"requires_root: {'yes' if step.requires_root else 'no'} | source: {step.source}"
        )
        print(f"            verify: {step.verification}")
    return 0


def _cmd_veil_status(_args: argparse.Namespace) -> int:
    status = build_veil_status()
    print("SEREIN VEIL")
    print()
    print("Tor")
    print(_tool_line("tor", status.tor.binary))
    print(f"  master unit    {_yes_no_unknown(status.tor.service.master_unit_active)}")
    print(f"  runtime unit   {_yes_no_unknown(status.tor.service.runtime_unit_active)}")
    print(f"  SOCKS          {_yes_no_unknown(status.tor.config.socks_port_configured)}")
    print(f"  control        {_yes_no_unknown(status.tor.config.control_port_configured)}")
    print(f"  usable         {_yes_no_unknown(status.tor.usable)}")
    print(_tool_line("torsocks", status.tor.torsocks))
    print(_tool_line("nyx", status.tor.nyx))
    print(_tool_line("obfs4proxy", status.tor.obfs4proxy))
    print()
    print("Browser")
    print(_tool_line("Tor Browser launcher", status.tor_browser.launcher))
    print("  isolated profile no (S6 never creates one)")
    print()
    print("Leak protection")
    print(f"  DNS isolation  {_yes_no_unknown(status.dns.dns_isolation_proven)}")
    print(f"  kill switch    {_yes_no_unknown(status.kill_switch.usable)}")
    print()
    print("Workspace")
    print(f"  privacy level  {status.workspace.privacy_level}")
    print(f"  usable         {_yes_no_unknown(status.workspace.usable)}")
    print()
    print("Whonix")
    print(f"  VM ready       {_yes_no_unknown(status.whonix.vm_readiness.usable)}")
    print(f"  Gateway image  {_yes_no_unknown(status.whonix.gateway_image_present)}")
    print(f"  Workstation image {_yes_no_unknown(status.whonix.workstation_image_present)}")
    print(f"  topology       {_yes_no_unknown(status.whonix.usable)}")
    return 0


def _cmd_veil_doctor(args: argparse.Namespace) -> int:
    report = run_veil_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN VEIL DOCTOR", report)
    return report.exit_code


def _cmd_veil_capabilities(args: argparse.Namespace) -> int:
    report = build_veil_capabilities()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print("SEREIN VEIL CAPABILITIES")
    print()
    for capability in report.capabilities:
        label = _VEIL_CAPABILITY_LABELS.get(capability.id, capability.id)
        usable = _yes_no_unknown(capability.usable)
        print(f"{label:<24}available={_yes_no_unknown(capability.available):<9}usable={usable}")
    return 0


def _cmd_veil_plan(args: argparse.Namespace) -> int:
    plan = build_veil_plan(getattr(args, "component", None))
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    header = "SEREIN VEIL PLAN"
    if getattr(args, "component", None):
        header += f" - {args.component}"
    print(header)
    print()
    for step in plan.actions:
        target = f" -> {step.target}" if step.target else ""
        current = f" (current: {step.current})" if step.current else ""
        print(f"  [{step.status:<7}] {step.component}.{step.action}: {step.tool}{target}{current}")
        print(f"            reason: {step.reason}")
        print(
            f"            risk: {step.risk} | reversible: {'yes' if step.reversible else 'no'} | "
            f"requires_root: {'yes' if step.requires_root else 'no'} | source: {step.source}"
        )
        print(f"            verify: {step.verification}")
    return 0


def _cmd_profile_list(args: argparse.Namespace) -> int:
    profiles = list_profiles()
    if args.json:
        print(json.dumps([p.to_dict() for p in profiles], indent=2, sort_keys=True))
        return 0

    print("SEREIN PROFILES")
    print(f"{'ID':<12}{'STATUS':<13}{'ACTIVE':<8}NAME")
    for profile in profiles:
        active = "yes" if profile.active else "no"
        print(f"{profile.id:<12}{profile.status:<13}{active:<8}{profile.name}")
    print()
    print("Note: profile activation is not implemented in S0; ACTIVE is always 'no'.")
    return 0


def _cmd_desktop_status(_args: argparse.Namespace) -> int:
    status = build_desktop_status()
    print("SEREIN DESKTOP")
    print()
    print(f"Profile        {status.profile_id}")
    print(f"Implementation {status.profile_status}")
    print()
    print("Session")
    print(f"  Desktop      {status.session.desktop_environment or 'unavailable'}")
    print(f"  Type         {status.session.session_type or 'unavailable'}")
    kwin = status.availability.kwin_wayland_installed or status.availability.kwin_x11_installed
    print(f"  KWin         {'detected' if kwin else 'unavailable'}")
    print(f"  SDDM         {'detected' if status.availability.sddm_installed else 'unavailable'}")
    print()
    print("Configuration")
    applied = "yes" if status.config.serein_preset_applied else "no"
    print(f"  Serein preset applied    {applied}")
    print()
    print("Compatibility")
    print(f"  Ubuntu target            {status.os_compatibility}")
    return 0


def _cmd_desktop_doctor(args: argparse.Namespace) -> int:
    report = run_desktop_checks()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return report.exit_code

    _print_doctor_report("SEREIN DESKTOP DOCTOR", report)
    return report.exit_code


def _cmd_desktop_plan(args: argparse.Namespace) -> int:
    plan = build_desktop_plan()
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0

    print("Desktop installation plan")
    print()
    print("Packages:")
    for pkg in plan.packages:
        print(f"  install {pkg}")
    print()
    print("System configuration:")
    for step in plan.system_configuration:
        print(f"  {step.action:<24} {step.detail}")
    print()
    print("User configuration:")
    for step in plan.user_configuration:
        print(f"  {step.action:<28} {step.detail}")
    print()
    print("Verification:")
    for check_id in plan.verification:
        print(f"  {check_id}")
    return 0


def _cmd_desktop_config_status(_args: argparse.Namespace) -> int:
    missing = {r.id for r in missing_resources()}
    print("SEREIN DESKTOP CONFIG RESOURCES")
    for resource in RESOURCES:
        state = "MISSING" if resource.id in missing else "present"
        print(f"[{state:7}] {resource.id:<22} -> {resource.target_path}")
    print()
    print("'present' means the file ships in this repository under desktop/;")
    print("it does not mean the file has been installed onto this host.")
    return 1 if missing else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serein", description="Serein OS control-plane CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Print the control-plane version").set_defaults(
        func=_cmd_version
    )
    subparsers.add_parser("status", help="Show a read-only workstation summary").set_defaults(
        func=_cmd_status
    )

    doctor_parser = subparsers.add_parser("doctor", help="Run foundation-level diagnostics")
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    doctor_parser.set_defaults(func=_cmd_doctor)

    hardware_parser = subparsers.add_parser("hardware", help="Hardware discovery")
    hardware_subparsers = hardware_parser.add_subparsers(dest="hardware_command", required=True)
    probe_parser = hardware_subparsers.add_parser("probe", help="Probe available hardware")
    probe_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    probe_parser.set_defaults(func=_cmd_hardware_probe)

    hardware_status_parser = hardware_subparsers.add_parser(
        "status", help="Show a read-only hardware policy summary"
    )
    hardware_status_parser.set_defaults(func=_cmd_hardware_status)

    hardware_doctor_parser = hardware_subparsers.add_parser(
        "doctor", help="Run hardware-level diagnostics"
    )
    hardware_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    hardware_doctor_parser.set_defaults(func=_cmd_hardware_doctor)

    hardware_capabilities_parser = hardware_subparsers.add_parser(
        "capabilities", help="Show what Serein can safely control on this host"
    )
    hardware_capabilities_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    hardware_capabilities_parser.set_defaults(func=_cmd_hardware_capabilities)

    hardware_plan_parser = hardware_subparsers.add_parser(
        "plan", help="Show the hardware resource-policy plan for a profile"
    )
    hardware_plan_parser.add_argument("profile", choices=VALID_PROFILES)
    hardware_plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    hardware_plan_parser.set_defaults(func=_cmd_hardware_plan)

    dev_parser = subparsers.add_parser("dev", help="Development workstation")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command", required=True)

    dev_subparsers.add_parser("status", help="Show development toolchain state").set_defaults(
        func=_cmd_dev_status
    )

    dev_doctor_parser = dev_subparsers.add_parser(
        "doctor", help="Run development-level diagnostics"
    )
    dev_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    dev_doctor_parser.set_defaults(func=_cmd_dev_doctor)

    dev_capabilities_parser = dev_subparsers.add_parser(
        "capabilities", help="Show which development stacks Serein can provision"
    )
    dev_capabilities_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    dev_capabilities_parser.set_defaults(func=_cmd_dev_capabilities)

    dev_plan_parser = dev_subparsers.add_parser(
        "plan", help="Show the development workstation plan"
    )
    dev_plan_parser.add_argument(
        "component", nargs="?", choices=DEV_VALID_COMPONENTS, default=None,
        help="Show only actions for this component (e.g. python, node, rust)",
    )
    dev_plan_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    dev_plan_parser.set_defaults(func=_cmd_dev_plan)

    ai_parser = subparsers.add_parser("ai", help="AI workstation")
    ai_subparsers = ai_parser.add_subparsers(dest="ai_command", required=True)

    ai_subparsers.add_parser("status", help="Show AI backend/runtime state").set_defaults(
        func=_cmd_ai_status
    )

    ai_doctor_parser = ai_subparsers.add_parser("doctor", help="Run AI-level diagnostics")
    ai_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    ai_doctor_parser.set_defaults(func=_cmd_ai_doctor)

    ai_capabilities_parser = ai_subparsers.add_parser(
        "capabilities", help="Show which AI stacks Serein can provision"
    )
    ai_capabilities_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    ai_capabilities_parser.set_defaults(func=_cmd_ai_capabilities)

    ai_plan_parser = ai_subparsers.add_parser(
        "plan", help="Show the AI workstation plan"
    )
    ai_plan_parser.add_argument(
        "component", nargs="?", choices=AI_VALID_COMPONENTS, default=None,
        help="Show only actions for this component (e.g. pytorch, inference, containers, voice)",
    )
    ai_plan_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    ai_plan_parser.set_defaults(func=_cmd_ai_plan)

    cyber_parser = subparsers.add_parser("cyber", help="Cybersecurity workspace")
    cyber_subparsers = cyber_parser.add_subparsers(dest="cyber_command", required=True)

    cyber_subparsers.add_parser(
        "status", help="Show cyber tool/isolation state"
    ).set_defaults(func=_cmd_cyber_status)

    cyber_doctor_parser = cyber_subparsers.add_parser(
        "doctor", help="Run cyber-level diagnostics"
    )
    cyber_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    cyber_doctor_parser.set_defaults(func=_cmd_cyber_doctor)

    cyber_capabilities_parser = cyber_subparsers.add_parser(
        "capabilities", help="Show which cyber stacks Serein can provision"
    )
    cyber_capabilities_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    cyber_capabilities_parser.set_defaults(func=_cmd_cyber_capabilities)

    cyber_plan_parser = cyber_subparsers.add_parser(
        "plan", help="Show the cyber workspace plan"
    )
    cyber_plan_parser.add_argument(
        "component", nargs="?", choices=CYBER_VALID_COMPONENTS, default=None,
        help="Show only actions for this component (host, toolbox, vm)",
    )
    cyber_plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    cyber_plan_parser.set_defaults(func=_cmd_cyber_plan)

    veil_parser = subparsers.add_parser("veil", help="Privacy isolation workspace")
    veil_subparsers = veil_parser.add_subparsers(dest="veil_command", required=True)

    veil_subparsers.add_parser(
        "status", help="Show Tor/privacy-workspace/Whonix state"
    ).set_defaults(func=_cmd_veil_status)

    veil_doctor_parser = veil_subparsers.add_parser(
        "doctor", help="Run Veil-level diagnostics"
    )
    veil_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    veil_doctor_parser.set_defaults(func=_cmd_veil_doctor)

    veil_capabilities_parser = veil_subparsers.add_parser(
        "capabilities", help="Show which privacy mechanisms Serein can provision"
    )
    veil_capabilities_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    veil_capabilities_parser.set_defaults(func=_cmd_veil_capabilities)

    veil_plan_parser = veil_subparsers.add_parser(
        "plan", help="Show the Veil privacy plan"
    )
    veil_plan_parser.add_argument(
        "component", nargs="?", choices=VEIL_VALID_COMPONENTS, default=None,
        help="Show only actions for this component (tor, workspace, whonix)",
    )
    veil_plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    veil_plan_parser.set_defaults(func=_cmd_veil_plan)

    profile_parser = subparsers.add_parser("profile", help="Profile management")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_list_parser = profile_subparsers.add_parser("list", help="List known profiles")
    profile_list_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    profile_list_parser.set_defaults(func=_cmd_profile_list)

    desktop_parser = subparsers.add_parser("desktop", help="Desktop (KDE Plasma) integration")
    desktop_subparsers = desktop_parser.add_subparsers(dest="desktop_command", required=True)

    desktop_subparsers.add_parser("status", help="Show desktop state").set_defaults(
        func=_cmd_desktop_status
    )

    desktop_doctor_parser = desktop_subparsers.add_parser(
        "doctor", help="Run desktop-level diagnostics"
    )
    desktop_doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    desktop_doctor_parser.set_defaults(func=_cmd_desktop_doctor)

    desktop_plan_parser = desktop_subparsers.add_parser(
        "plan", help="Show the desktop installation plan"
    )
    desktop_plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    desktop_plan_parser.set_defaults(func=_cmd_desktop_plan)

    desktop_config_parser = desktop_subparsers.add_parser("config", help="Desktop config resources")
    desktop_config_subparsers = desktop_config_parser.add_subparsers(
        dest="desktop_config_command", required=True
    )
    desktop_config_subparsers.add_parser(
        "status", help="Show which desktop config resources ship in this repository"
    ).set_defaults(func=_cmd_desktop_config_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # last-resort guard: no command may traceback at users
        print(f"serein: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
