"""AI subsystem tests. Every detection call uses a FakeCommandRunner and
(where relevant) an injected root/home/env — never the real host's PATH,
filesystem, or environment, so tests are independent of whatever
happens to be installed on the machine running them."""

from __future__ import annotations

import json

import pytest

from serein.ai.amd import detect_amd_status
from serein.ai.backend import classify_backend
from serein.ai.capabilities import build_ai_capabilities
from serein.ai.containers import detect_ai_container_status
from serein.ai.doctor import run_ai_checks
from serein.ai.inference import detect_inference_status
from serein.ai.intel import detect_intel_status
from serein.ai.models import (
    AI_CAPABILITIES_SCHEMA_VERSION,
    AI_PLAN_SCHEMA_VERSION,
    classify_vram_tier,
)
from serein.ai.nvidia import detect_nvidia_status
from serein.ai.packages import all_tools
from serein.ai.planner import VALID_COMPONENTS, build_ai_plan
from serein.ai.python_env import detect_python_ai_packages, probe_python_package
from serein.ai.pytorch import detect_pytorch_status, select_pytorch_backend
from serein.ai.storage import build_ai_storage_info
from serein.development.runner import CommandResult
from serein.doctor.models import CheckStatus
from serein.hardware.models import GPUClassification, GPUDevice, GPUPolicyInfo


class FakeCommandRunner:
    """Maps a binary name to a canned CommandResult (or None = "not
    found"). Records every call for tests that need to assert on
    invocation without ever actually running anything."""

    def __init__(self, responses: dict[str, CommandResult | None]):
        self._responses = responses
        self.calls: list[list[str]] = []

    def run(self, args, timeout: float = 3.0):
        self.calls.append(list(args))
        binary = args[0]
        if binary not in self._responses:
            return None
        return self._responses[binary]


def _ok(binary: str, stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _fail(binary: str) -> CommandResult:
    return CommandResult(returncode=1, stdout="", stderr="not found")


def _gpu_policy(
    classifications: list[GPUClassification] | None = None,
    nvidia_present: bool = False,
    nvidia_module: bool = False,
    amdgpu_module: bool = False,
    hybrid: bool | None = False,
) -> GPUPolicyInfo:
    classifications = classifications or []
    return GPUPolicyInfo(
        hybrid=hybrid,
        hybrid_confidence="high",
        classifications=classifications,
        nvidia_present=nvidia_present,
        nvidia_kernel_module_loaded=nvidia_module,
        amdgpu_kernel_module_loaded=amdgpu_module,
        integrated_count=sum(1 for c in classifications if c.kind == "integrated"),
        discrete_count=sum(1 for c in classifications if c.kind == "discrete"),
    )


class TestVRAMTier:
    @pytest.mark.parametrize(
        "mib,expected",
        [
            (2048, "<6GiB"),
            (6144, "6-8GiB"),
            (8192, "8-12GiB"),
            (12288, "12-24GiB"),
            (24576, "24GiB+"),
            (49152, "24GiB+"),
        ],
    )
    def test_tier_boundaries(self, mib, expected):
        assert classify_vram_tier(mib) == expected


class TestBackend:
    def test_nvidia_only(self):
        gpus = [GPUDevice(vendor="NVIDIA", model="0x2684", kind="discrete")]
        policy = _gpu_policy(
            [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
        )
        info = classify_backend(gpus, policy)
        assert info.primary == "nvidia_cuda"
        assert info.primary_confidence == "high"

    def test_amd_discrete(self):
        gpus = [GPUDevice(vendor="AMD", model="0x744c", kind="discrete")]
        policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        info = classify_backend(gpus, policy)
        assert info.primary == "amd_rocm"
        assert info.primary_confidence == "medium"

    def test_amd_apu_low_confidence(self):
        gpus = [GPUDevice(vendor="AMD", model="0x1638", kind="integrated")]
        policy = _gpu_policy([GPUClassification("AMD", "integrated", "medium")])
        info = classify_backend(gpus, policy)
        assert info.primary == "amd_rocm"
        assert info.primary_confidence == "low"

    def test_intel_discrete_arc(self):
        gpus = [GPUDevice(vendor="Intel", model="0x56a0", kind="discrete")]
        policy = _gpu_policy([GPUClassification("Intel", "discrete", "high")])
        info = classify_backend(gpus, policy)
        assert info.primary == "intel_gpu"

    def test_intel_igpu(self):
        gpus = [GPUDevice(vendor="Intel", model="0x9a49", kind="integrated")]
        policy = _gpu_policy([GPUClassification("Intel", "integrated", "medium")])
        info = classify_backend(gpus, policy)
        assert info.primary == "intel_gpu"

    def test_unrecognized_vendor_is_unknown_not_cpu(self):
        gpus = [GPUDevice(vendor="0x1234", model="0xabcd", kind="unknown")]
        policy = _gpu_policy([GPUClassification("0x1234", "unknown", "low")])
        info = classify_backend(gpus, policy)
        assert info.primary == "unknown"

    def test_no_gpu_is_cpu(self):
        info = classify_backend([], _gpu_policy())
        assert info.primary == "cpu"
        assert info.primary_confidence == "high"

    def test_nvidia_priority_over_amd_hybrid(self):
        gpus = [
            GPUDevice(vendor="AMD", model="0x1638", kind="integrated"),
            GPUDevice(vendor="NVIDIA", model="0x2684", kind="discrete"),
        ]
        policy = _gpu_policy(
            [
                GPUClassification("AMD", "integrated", "medium"),
                GPUClassification("NVIDIA", "discrete", "high"),
            ],
            nvidia_present=True,
            hybrid=True,
        )
        info = classify_backend(gpus, policy)
        assert info.primary == "nvidia_cuda"
        assert info.hybrid is True

    def test_nvidia_priority_over_intel_hybrid(self):
        gpus = [
            GPUDevice(vendor="Intel", model="0x9a49", kind="integrated"),
            GPUDevice(vendor="NVIDIA", model="0x2684", kind="discrete"),
        ]
        policy = _gpu_policy(
            [
                GPUClassification("Intel", "integrated", "medium"),
                GPUClassification("NVIDIA", "discrete", "high"),
            ],
            nvidia_present=True,
            hybrid=True,
        )
        info = classify_backend(gpus, policy)
        assert info.primary == "nvidia_cuda"

    def test_multiple_nvidia_gpus_still_nvidia(self):
        gpus = [
            GPUDevice(vendor="NVIDIA", model="0x2684", kind="discrete"),
            GPUDevice(vendor="NVIDIA", model="0x2684", kind="discrete"),
        ]
        policy = _gpu_policy(
            [
                GPUClassification("NVIDIA", "discrete", "high"),
                GPUClassification("NVIDIA", "discrete", "high"),
            ],
            nvidia_present=True,
        )
        info = classify_backend(gpus, policy)
        assert info.primary == "nvidia_cuda"
        assert len(info.candidates) == 2

    def test_hardware_backend_does_not_reprobe_drm(self):
        # classify_backend takes pre-computed GPU data only - no root/path
        # arguments exist, so it cannot re-probe /sys/class/drm itself.
        import inspect

        sig = inspect.signature(classify_backend)
        assert list(sig.parameters) == ["gpus", "gpu_policy"]


class TestNvidia:
    def test_no_hardware(self):
        status = detect_nvidia_status(_gpu_policy(), runner=FakeCommandRunner({}))
        assert status.hardware_present is False
        assert status.driver_version is None
        assert status.cuda_toolkit_installed is False

    def test_hardware_no_driver(self):
        policy = _gpu_policy(nvidia_present=True)
        status = detect_nvidia_status(policy, runner=FakeCommandRunner({}))
        assert status.hardware_present is True
        assert status.driver_version is None
        assert status.cuda_driver_api_version is None

    def test_driver_present_no_toolkit(self, tmp_path):
        policy = _gpu_policy(nvidia_present=True)
        runner = FakeCommandRunner({
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        status = detect_nvidia_status(policy, runner=runner, root=tmp_path)
        assert status.driver_version == "580.65.06"
        assert status.cuda_driver_api_version == "13.0"
        assert status.cuda_toolkit_installed is False

    def test_cuda_driver_version_never_implies_toolkit(self, tmp_path):
        # The exact S4 defect class this module must avoid: a
        # driver-reported CUDA version is not toolkit installation proof.
        policy = _gpu_policy(nvidia_present=True)
        runner = FakeCommandRunner({
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        status = detect_nvidia_status(policy, runner=runner, root=tmp_path)
        assert status.cuda_driver_api_version == "13.0"
        assert status.cuda_toolkit_installed is False
        assert status.nvcc.installed is False

    def test_toolkit_via_nvcc(self, tmp_path):
        policy = _gpu_policy(nvidia_present=True)
        runner = FakeCommandRunner({
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
            "nvcc": _ok("nvcc", "Cuda compilation tools, release 12.6, V12.6.85"),
        })
        status = detect_nvidia_status(policy, runner=runner, root=tmp_path)
        assert status.cuda_toolkit_installed is True

    def test_toolkit_via_dpkg_package_state(self, tmp_path):
        runner = FakeCommandRunner({"dpkg-query": _ok("dpkg-query", "install ok installed")})
        policy = _gpu_policy(nvidia_present=True)
        status = detect_nvidia_status(policy, runner=runner, root=tmp_path)
        assert status.cuda_toolkit_installed is True

    def test_empty_marker_directory_is_not_installed(self, tmp_path):
        # S4R Section 16/19 regression: a bare marker (empty directory,
        # no nvcc, no dpkg evidence) must NOT prove installation.
        (tmp_path / "usr" / "local" / "cuda").mkdir(parents=True)
        policy = _gpu_policy(nvidia_present=True)
        status = detect_nvidia_status(policy, runner=FakeCommandRunner({}), root=tmp_path)
        assert status.cuda_toolkit_installed is False
        assert status.cuda_toolkit_marker_present is True

    def test_stale_marker_with_no_evidence_is_not_installed(self, tmp_path):
        # A marker existing (stale symlink case simulated as a plain
        # directory - real symlink creation is awkward/unportable in
        # fixtures, see the S4R brief's own hedge on this) with no
        # nvcc/dpkg evidence must still not prove installation.
        (tmp_path / "usr" / "local" / "cuda").mkdir(parents=True)
        runner = FakeCommandRunner({"dpkg-query": CommandResult(1, "", "no packages found")})
        policy = _gpu_policy(nvidia_present=True)
        status = detect_nvidia_status(policy, runner=runner, root=tmp_path)
        assert status.cuda_toolkit_installed is False
        assert status.cuda_toolkit_marker_present is True

    def test_marker_present_but_installed_true_when_nvcc_also_present(self, tmp_path):
        (tmp_path / "usr" / "local" / "cuda").mkdir(parents=True)
        runner = FakeCommandRunner({"nvcc": _ok("nvcc", "release 12.6, V12.6.85")})
        policy = _gpu_policy(nvidia_present=True)
        status = detect_nvidia_status(policy, runner=runner, root=tmp_path)
        assert status.cuda_toolkit_installed is True
        assert status.cuda_toolkit_marker_present is True

    def test_multiple_toolkit_dirs_reported(self, tmp_path):
        (tmp_path / "usr" / "local" / "cuda-12.4").mkdir(parents=True)
        (tmp_path / "usr" / "local" / "cuda-12.6").mkdir(parents=True)
        policy = _gpu_policy(nvidia_present=True)
        status = detect_nvidia_status(policy, runner=FakeCommandRunner({}), root=tmp_path)
        assert set(status.cuda_toolkit_dirs) == {"cuda-12.4", "cuda-12.6"}

    def test_vram_query(self, tmp_path):
        policy = _gpu_policy(nvidia_present=True)
        runner = FakeCommandRunner({
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args[:2] == ["nvidia-smi", "--query-gpu=memory.total"]:
                    return _ok("nvidia-smi", "8192\n")
                return super().run(args, timeout)

        vram_runner = _Runner(runner._responses)
        status = detect_nvidia_status(policy, runner=vram_runner, root=tmp_path)
        assert len(status.vram) == 1
        assert status.vram[0].total_mib == 8192
        assert status.vram[0].tier == "8-12GiB"

    def test_container_toolkit_probe(self, tmp_path):
        policy = _gpu_policy(nvidia_present=True)
        runner = FakeCommandRunner(
            {"nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0")}
        )
        status = detect_nvidia_status(policy, runner=runner, root=tmp_path)
        assert status.nvidia_ctk.installed is True


class TestAmd:
    def test_no_hardware(self):
        status = detect_amd_status(_gpu_policy(), runner=FakeCommandRunner({}))
        assert status.hardware_present is False
        assert status.rocm_support.gpu_enumerated is None

    def test_hardware_no_rocminfo_is_unknown_not_true(self):
        policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        status = detect_amd_status(policy, runner=FakeCommandRunner({}))
        assert status.hardware_present is True
        assert status.rocm_support.gpu_enumerated is None
        assert status.rocm_support.confidence == "low"

    def test_rocminfo_confirms_gpu_agent(self):
        policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        rocminfo_output = (
            "Agent 1\n  Device Type:             CPU\n"
            "Agent 2\n  Device Type:             GPU\n"
        )
        runner = FakeCommandRunner({
            "rocminfo": _ok("rocminfo", rocminfo_output),
        })
        status = detect_amd_status(policy, runner=runner)
        assert status.rocm_support.gpu_enumerated is True
        assert status.rocm_support.confidence == "high"

    def test_rocminfo_reports_no_gpu_agent(self):
        policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        runner = FakeCommandRunner({
            "rocminfo": _ok("rocminfo", "Agent 1\n  Device Type:             CPU\n"),
        })
        status = detect_amd_status(policy, runner=runner)
        assert status.rocm_support.gpu_enumerated is False
        assert status.rocm_support.confidence == "high"

    def test_never_guesses_from_vendor_id_alone(self):
        # Hardware present, no runtime evidence at all -> must remain
        # unknown, never silently True.
        policy = _gpu_policy([GPUClassification("AMD", "unknown", "low")])
        status = detect_amd_status(policy, runner=FakeCommandRunner({}))
        assert status.rocm_support.gpu_enumerated is not True


class TestIntel:
    def test_no_hardware(self):
        status = detect_intel_status(_gpu_policy())
        assert status.hardware_present is False
        assert status.kind is None

    def test_igpu(self):
        policy = _gpu_policy([GPUClassification("Intel", "integrated", "medium")])
        status = detect_intel_status(policy)
        assert status.hardware_present is True
        assert status.kind == "integrated"

    def test_arc_discrete(self):
        policy = _gpu_policy([GPUClassification("Intel", "discrete", "high")])
        status = detect_intel_status(policy)
        assert status.kind == "discrete"

    def test_unknown_topology_stays_unknown(self):
        policy = _gpu_policy([GPUClassification("Intel", "unknown", "low")])
        status = detect_intel_status(policy)
        assert status.kind == "unknown"

    def test_igpu_and_arc_not_conflated(self):
        # Two Intel devices, one arc one igpu - the discrete one should
        # be preferred/reported, never averaged/conflated into one label.
        policy = _gpu_policy([
            GPUClassification("Intel", "integrated", "medium"),
            GPUClassification("Intel", "discrete", "high"),
        ])
        status = detect_intel_status(policy)
        assert status.kind == "discrete"


class TestPythonEnv:
    def test_package_present(self):
        runner = FakeCommandRunner({"python3": _ok("python3", "4.44.2")})
        status = probe_python_package("transformers", runner=runner)
        assert status.installed is True
        assert status.version == "4.44.2"

    def test_package_absent(self):
        runner = FakeCommandRunner({"python3": _fail("python3")})
        status = probe_python_package("transformers", runner=runner)
        assert status.installed is False

    def test_python3_missing_entirely(self):
        status = probe_python_package("transformers", runner=FakeCommandRunner({}))
        assert status.installed is False

    def test_detect_all_packages(self):
        runner = FakeCommandRunner({"python3": _ok("python3", "1.0.0")})
        status = detect_python_ai_packages(runner=runner)
        assert status.transformers.installed
        assert status.accelerate.installed
        assert status.safetensors.installed
        assert status.huggingface_hub.installed
        assert status.vllm.installed
        assert status.onnxruntime.installed
        assert status.tensorrt.installed
        assert status.bitsandbytes.installed

    def test_never_imports_the_package_itself(self):
        # The probe code must only ever reference importlib.metadata, not
        # the package's own import name, in the subprocess command.
        runner = FakeCommandRunner({"python3": _ok("python3", "1.0.0")})
        probe_python_package("transformers", runner=runner)
        code = runner.calls[-1][-1]
        assert "importlib.metadata" in code
        assert "import transformers" not in code


class TestPyTorch:
    def test_absent(self):
        status = detect_pytorch_status(runner=FakeCommandRunner({"python3": _fail("python3")}))
        assert status.installed.installed is False
        assert status.build_backend is None

    def test_cpu_build(self):
        payload = json.dumps({"version": "2.5.1+cpu", "cuda": None, "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        status = detect_pytorch_status(runner=runner)
        assert status.installed.installed is True
        assert status.build_backend == "cpu"
        assert status.build_backend_version is None

    def test_cuda_build(self):
        payload = json.dumps({"version": "2.5.1+cu124", "cuda": "12.4", "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        status = detect_pytorch_status(runner=runner)
        assert status.build_backend == "cuda"
        assert status.build_backend_version == "12.4"

    def test_rocm_build(self):
        payload = json.dumps({"version": "2.5.1+rocm6.1", "cuda": None, "hip": "6.1"})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        status = detect_pytorch_status(runner=runner)
        assert status.build_backend == "rocm"
        assert status.build_backend_version == "6.1"

    def test_malformed_output_degrades_to_not_installed(self):
        runner = FakeCommandRunner({"python3": _ok("python3", "not json at all")})
        status = detect_pytorch_status(runner=runner)
        assert status.installed.installed is False

    def test_never_calls_cuda_is_available(self):
        payload = json.dumps({"version": "2.5.1+cu124", "cuda": "12.4", "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        detect_pytorch_status(runner=runner)
        code = runner.calls[-1][-1]
        assert "is_available" not in code


class TestSelectPytorchBackend:
    """S4R Section 4-9/41/63: the shared runtime-gated backend decision.
    A hardware candidate alone must never be sufficient for an
    accelerator-specific target - only proven driver/runtime readiness
    is."""

    def test_no_gpu_is_cpu_ready(self):
        gpu_policy = _gpu_policy()
        backend = classify_backend([], gpu_policy)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "cpu"
        assert decision.status == "APPLY"

    def test_unknown_vendor_is_cpu_ready(self):
        gpus = [GPUDevice(vendor="0x1234", kind="unknown")]
        gpu_policy = _gpu_policy([GPUClassification("0x1234", "unknown", "low")])
        backend = classify_backend(gpus, gpu_policy)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "cpu"
        assert decision.status == "APPLY"

    def test_nvidia_hardware_no_driver_is_blocked_not_cpu(self):
        gpus = [GPUDevice(vendor="NVIDIA", kind="discrete")]
        gpu_policy = _gpu_policy(
            [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
        )
        backend = classify_backend(gpus, gpu_policy)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        # Never silently substitutes cpu while a real accelerator
        # candidate's readiness is unresolved (S4R Section 5).
        assert decision.target == "cuda"
        assert decision.status == "BLOCKED"

    def test_nvidia_driver_proven_is_cuda_ready(self):
        gpus = [GPUDevice(vendor="NVIDIA", kind="discrete")]
        gpu_policy = _gpu_policy(
            [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
        )
        backend = classify_backend(gpus, gpu_policy)
        runner = FakeCommandRunner({
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        nvidia = detect_nvidia_status(gpu_policy, runner=runner)
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "cuda"
        assert decision.status == "APPLY"

    def test_amd_gpu_enumerated_is_blocked_not_ready(self):
        # rocminfo enumerating a GPU proves ROCm/HSA hardware
        # recognition, NOT PyTorch-wheel/MIOpen framework compatibility
        # - so this must stay BLOCKED, never auto-selected as ready.
        gpus = [GPUDevice(vendor="AMD", kind="discrete")]
        gpu_policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        backend = classify_backend(gpus, gpu_policy)
        runner = FakeCommandRunner({
            "rocminfo": _ok("rocminfo", "Agent 1\n  Device Type:             GPU\n"),
        })
        amd = detect_amd_status(gpu_policy, runner=runner)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "rocm"
        assert decision.status == "BLOCKED"

    def test_amd_confirmed_unsupported_falls_back_to_cpu(self):
        gpus = [GPUDevice(vendor="AMD", kind="discrete")]
        gpu_policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        backend = classify_backend(gpus, gpu_policy)
        runner = FakeCommandRunner({
            "rocminfo": _ok("rocminfo", "Agent 1\n  Device Type:             CPU\n"),
        })
        amd = detect_amd_status(gpu_policy, runner=runner)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "cpu"
        assert decision.status == "APPLY"

    def test_amd_no_runtime_is_blocked(self):
        gpus = [GPUDevice(vendor="AMD", kind="discrete")]
        gpu_policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        backend = classify_backend(gpus, gpu_policy)
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "rocm"
        assert decision.status == "BLOCKED"

    def test_intel_gpu_is_blocked_never_silently_cpu(self):
        # Section 8/45: do not automatically map intel_gpu -> cpu as if
        # that were "the Intel strategy" - Intel is a real candidate,
        # just one whose XPU compatibility is unresolved.
        gpus = [GPUDevice(vendor="Intel", kind="discrete")]
        gpu_policy = _gpu_policy([GPUClassification("Intel", "discrete", "high")])
        backend = classify_backend(gpus, gpu_policy)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "xpu"
        assert decision.status == "BLOCKED"

    def test_intel_igpu_also_blocked_not_conflated_with_arc(self):
        gpus = [GPUDevice(vendor="Intel", kind="integrated")]
        gpu_policy = _gpu_policy([GPUClassification("Intel", "integrated", "medium")])
        backend = classify_backend(gpus, gpu_policy)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert decision.target == "xpu"
        assert decision.status == "BLOCKED"

    def test_invariant_cuda_target_ready_implies_driver_not_false(self):
        """Section 41/63 invariant, exercised across a matrix of
        scenarios: target=='cuda' and status=='APPLY' must never occur
        without nvidia.driver_version being set."""
        gpus = [GPUDevice(vendor="NVIDIA", kind="discrete")]
        gpu_policy = _gpu_policy(
            [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
        )
        backend = classify_backend(gpus, gpu_policy)
        intel = detect_intel_status(gpu_policy)
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        scenarios = [
            FakeCommandRunner({}),
            FakeCommandRunner({
                "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
            }),
        ]
        for runner in scenarios:
            nvidia = detect_nvidia_status(gpu_policy, runner=runner)
            decision = select_pytorch_backend(backend, nvidia, amd, intel)
            if decision.target == "cuda" and decision.status == "APPLY":
                assert nvidia.driver_version is not None

    def test_invariant_rocm_target_ready_never_occurs(self):
        """Given this pass's Option C choice (no reliable PyTorch-ROCm
        compatibility source exists), target=='rocm' must never be
        paired with status=='APPLY' - framework compatibility is always
        conservatively unresolved. See docs/ai/amd-rocm-strategy.md."""
        gpus = [GPUDevice(vendor="AMD", kind="discrete")]
        gpu_policy = _gpu_policy([GPUClassification("AMD", "discrete", "high")])
        backend = classify_backend(gpus, gpu_policy)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        scenarios = [
            FakeCommandRunner({}),
            FakeCommandRunner({
                "rocminfo": _ok("rocminfo", "Agent 1\n  Device Type:             GPU\n"),
            }),
            FakeCommandRunner({
                "rocminfo": _ok("rocminfo", "Agent 1\n  Device Type:             CPU\n"),
            }),
        ]
        for runner in scenarios:
            amd = detect_amd_status(gpu_policy, runner=runner)
            decision = select_pytorch_backend(backend, nvidia, amd, intel)
            assert not (decision.target == "rocm" and decision.status == "APPLY")

    def test_invariant_xpu_target_ready_never_occurs(self):
        """Same reasoning for Intel: xpu_compatibility is always
        "unknown" in this pass, so target=='xpu' must never be paired
        with status=='APPLY'."""
        gpus = [GPUDevice(vendor="Intel", kind="discrete")]
        gpu_policy = _gpu_policy([GPUClassification("Intel", "discrete", "high")])
        backend = classify_backend(gpus, gpu_policy)
        nvidia = detect_nvidia_status(gpu_policy, runner=FakeCommandRunner({}))
        amd = detect_amd_status(gpu_policy, runner=FakeCommandRunner({}))
        intel = detect_intel_status(gpu_policy)
        decision = select_pytorch_backend(backend, nvidia, amd, intel)
        assert not (decision.target == "xpu" and decision.status == "APPLY")


class TestInference:
    def test_ollama_absent(self):
        status = detect_inference_status(runner=FakeCommandRunner({}))
        assert status.ollama.binary.installed is False
        assert status.ollama.service_active is None

    def test_ollama_present_service_active(self):
        runner = FakeCommandRunner({
            "ollama": _ok("ollama", "ollama version is 0.4.1"),
            "systemctl": _ok("systemctl", "active"),
        })
        status = detect_inference_status(runner=runner)
        assert status.ollama.binary.installed is True
        assert status.ollama.service_active is True

    def test_ollama_present_service_inactive(self):
        runner = FakeCommandRunner({
            "ollama": _ok("ollama", "ollama version is 0.4.1"),
            "systemctl": _ok("systemctl", "inactive"),
        })
        status = detect_inference_status(runner=runner)
        assert status.ollama.service_active is False

    def test_llama_cpp_absent(self):
        status = detect_inference_status(runner=FakeCommandRunner({}))
        assert status.llama_cpp.llama_cli.installed is False
        assert status.llama_cpp.llama_server.installed is False

    def test_llama_cpp_cli_only(self):
        runner = FakeCommandRunner({"llama-cli": _ok("llama-cli", "version: 1")})
        status = detect_inference_status(runner=runner)
        assert status.llama_cpp.llama_cli.installed is True
        assert status.llama_cpp.llama_server.installed is False

    def test_both_ollama_and_llama_cpp_coexist(self):
        runner = FakeCommandRunner({
            "ollama": _ok("ollama", "ollama version is 0.4.1"),
            "llama-cli": _ok("llama-cli", "version: 1"),
            "llama-server": _ok("llama-server", "version: 1"),
        })
        status = detect_inference_status(runner=runner)
        assert status.ollama.binary.installed and status.llama_cpp.llama_cli.installed

    def test_never_starts_ollama_service(self):
        runner = FakeCommandRunner({
            "ollama": _ok("ollama", "ollama version is 0.4.1"),
            "systemctl": _ok("systemctl", "active"),
        })
        detect_inference_status(runner=runner)
        for call in runner.calls:
            assert "start" not in call
            assert "restart" not in call


class TestContainers:
    def test_podman_only(self):
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.0.0")})
        status = detect_ai_container_status(runner=runner)
        assert status.podman.installed and not status.docker.installed

    def test_docker_only(self):
        runner = FakeCommandRunner({"docker": _ok("docker", "Docker version 27.0.0")})
        status = detect_ai_container_status(runner=runner)
        assert status.docker.installed

    def test_neither(self):
        status = detect_ai_container_status(runner=FakeCommandRunner({}))
        assert not status.podman.installed and not status.docker.installed

    def test_nvidia_container_toolkit(self):
        runner = FakeCommandRunner(
            {"nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0")}
        )
        status = detect_ai_container_status(runner=runner)
        assert status.nvidia_container_toolkit.installed is True

    def test_cdi_marker_etc(self, tmp_path):
        (tmp_path / "etc" / "cdi").mkdir(parents=True)
        (tmp_path / "etc" / "cdi" / "nvidia.yaml").write_text("")
        status = detect_ai_container_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert status.cdi_nvidia_generated is True

    def test_cdi_marker_absent(self, tmp_path):
        status = detect_ai_container_status(runner=FakeCommandRunner({}), root=tmp_path)
        assert status.cdi_nvidia_generated is False

    def test_never_creates_a_container(self):
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.0.0")})
        detect_ai_container_status(runner=runner)
        for call in runner.calls:
            assert "run" not in call
            assert "create" not in call


class TestStorage:
    def test_defaults_when_unset(self, tmp_path):
        info = build_ai_storage_info(env={}, home=tmp_path)
        assert info.hf_home == "~/.cache/huggingface"
        assert info.hf_home_is_default is True
        assert info.ollama_models == "~/.ollama/models"
        assert info.ollama_models_is_default is True

    def test_hf_home_override(self, tmp_path):
        custom = tmp_path / "custom-hf"
        info = build_ai_storage_info(env={"HF_HOME": str(custom)}, home=tmp_path)
        assert info.hf_home_is_default is False
        assert str(tmp_path) not in info.hf_home or info.hf_home.startswith("~/")

    def test_ollama_models_override(self, tmp_path):
        custom = tmp_path / "custom-ollama"
        info = build_ai_storage_info(env={"OLLAMA_MODELS": str(custom)}, home=tmp_path)
        assert info.ollama_models_is_default is False

    def test_never_leaks_real_home_path(self, tmp_path):
        info = build_ai_storage_info(env={}, home=tmp_path)
        assert str(tmp_path) not in info.hf_home
        assert str(tmp_path) not in info.ollama_models

    def test_low_space_warning_when_below_threshold(self, tmp_path, monkeypatch):
        import shutil

        (tmp_path / ".cache" / "huggingface").mkdir(parents=True)

        class _Usage:
            free = 1024

        monkeypatch.setattr(shutil, "disk_usage", lambda _p: _Usage())
        info = build_ai_storage_info(env={}, home=tmp_path)
        assert info.low_space_warning is True

    def test_no_warning_when_free_space_ample(self, tmp_path, monkeypatch):
        import shutil

        (tmp_path / ".cache" / "huggingface").mkdir(parents=True)

        class _Usage:
            free = 100 * 1024 * 1024 * 1024

        monkeypatch.setattr(shutil, "disk_usage", lambda _p: _Usage())
        info = build_ai_storage_info(env={}, home=tmp_path)
        assert info.low_space_warning is False

    def test_free_bytes_none_when_path_undeterminable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "serein.ai.storage._nearest_existing_ancestor", lambda _p: None
        )
        info = build_ai_storage_info(env={}, home=tmp_path)
        assert info.cache_free_bytes is None
        assert info.low_space_warning is False


class TestPackages:
    def test_no_duplicate_ids(self):
        tools = all_tools()
        ids = [t.id for t in tools]
        assert len(ids) == len(set(ids))

    def test_every_tool_has_a_recognized_source_type(self):
        allowed = {
            "ubuntu-repository", "official-upstream-repository", "official-upstream-binary",
            "language-bootstrap-tool", "user-installed", "optional", "python-package-index",
        }
        for tool in all_tools():
            assert tool.source_type in allowed

    def test_ffmpeg_is_ubuntu_repository(self):
        ffmpeg = next(t for t in all_tools() if t.id == "ffmpeg")
        assert ffmpeg.source_type == "ubuntu-repository"
        assert ffmpeg.package == "ffmpeg"

    def test_torch_is_python_package_index_not_apt(self):
        torch = next(t for t in all_tools() if t.id == "torch")
        assert torch.source_type == "python-package-index"

    def test_no_custom_cuda_or_rocm_replacement_tools(self):
        # Section 3: S4 must not invent a custom CUDA/ROCm/tensor runtime.
        ids = {t.id for t in all_tools()}
        assert "serein-cuda" not in ids
        assert "serein-rocm" not in ids
        assert "serein-tensor-runtime" not in ids

    def test_optional_packages_not_in_pytorch_baseline_defaults(self):
        # bitsandbytes/flash-attn/datasets/peft/trl must be declared
        # (documented) but never required=True style defaults - S4 has
        # no "requires_root=True implies default" concept, but they must
        # exist only in the *_optional groups, never PYTHON_AI_BASE_TOOLS.
        from serein.ai.packages import PYTHON_AI_BASE_TOOLS

        base_ids = {t.id for t in PYTHON_AI_BASE_TOOLS}
        for optional_id in ("bitsandbytes", "flash-attn", "datasets", "peft", "trl"):
            assert optional_id not in base_ids

    def test_ollama_requires_root(self):
        # S4R Section 36-39: the official installer is system-level
        # (systemd service, system user/group, /usr/local/bin), never
        # a quiet user-level install.
        ollama = next(t for t in all_tools() if t.id == "ollama")
        assert ollama.requires_root is True

    def test_ipex_not_in_manifest(self):
        # S4R Section 32/33: Intel Extension for PyTorch is not
        # Serein's recommended path; no separate tool entry exists.
        ids = {t.id for t in all_tools()}
        assert "intel-extension-for-pytorch" not in ids

    def test_cuda_toolkit_source_is_ubuntu_repository(self):
        # S4R Section 20/60: verified live against Ubuntu 26.04's own
        # archive - see docs/validation/s4/ubuntu-package-validation.md.
        toolkit = next(t for t in all_tools() if t.id == "cuda-toolkit")
        assert toolkit.source_type == "ubuntu-repository"
        assert toolkit.package == "cuda-toolkit"

    def test_rocm_source_is_ubuntu_repository(self):
        rocm = next(t for t in all_tools() if t.id == "rocm")
        assert rocm.source_type == "ubuntu-repository"
        assert rocm.package == "rocm"

    def test_nvidia_container_toolkit_source_remains_third_party(self):
        # Confirmed genuinely absent from Ubuntu's archive - see
        # docs/validation/s4/ubuntu-package-validation.md.
        toolkit = next(t for t in all_tools() if t.id == "nvidia-container-toolkit")
        assert toolkit.source_type == "official-upstream-repository"


class TestCapabilities:
    def test_schema_version(self):
        report = build_ai_capabilities(runner=FakeCommandRunner({}))
        assert report.schema_version == AI_CAPABILITIES_SCHEMA_VERSION

    def test_all_sixteen_ids_present_once(self):
        report = build_ai_capabilities(runner=FakeCommandRunner({}))
        ids = [c.id for c in report.capabilities]
        expected = {
            "nvidia_hardware", "nvidia_driver", "cuda_runtime", "cuda_toolkit",
            "rocm_runtime", "intel_gpu_runtime", "pytorch", "pytorch_cuda",
            "pytorch_rocm", "pytorch_cpu", "ollama", "llama_cpp", "vllm",
            "onnxruntime", "tensorrt", "ai_container_runtime",
        }
        assert set(ids) == expected
        assert len(ids) == len(set(ids))

    def test_nvidia_hardware_presence_never_implies_cuda_ready(self, tmp_path, monkeypatch):
        # High-severity blocker regression (Section 119).
        import serein.ai.capabilities as caps_mod

        monkeypatch.setattr(
            caps_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            caps_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        report = build_ai_capabilities(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["nvidia_hardware"].installed is True
        assert by_id["cuda_toolkit"].installed is False
        assert by_id["cuda_runtime"].installed is False

    def test_nvidia_smi_cuda_field_never_proves_toolkit(self, tmp_path, monkeypatch):
        import serein.ai.capabilities as caps_mod

        monkeypatch.setattr(
            caps_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            caps_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        runner = FakeCommandRunner({
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["cuda_runtime"].installed is True
        assert by_id["cuda_toolkit"].installed is False

    def test_amd_vendor_alone_never_marks_rocm_usable(self, tmp_path, monkeypatch):
        import serein.ai.capabilities as caps_mod

        monkeypatch.setattr(
            caps_mod, "detect_gpus", lambda root: [GPUDevice(vendor="AMD", kind="discrete")]
        )
        monkeypatch.setattr(
            caps_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy([GPUClassification("AMD", "discrete", "high")]),
        )
        report = build_ai_capabilities(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["rocm_runtime"].usable is not True

    def test_pytorch_cpu_usable_when_installed(self):
        payload = json.dumps({"version": "2.5.1+cpu", "cuda": None, "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        report = build_ai_capabilities(runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["pytorch_cpu"].installed is True
        assert by_id["pytorch_cpu"].usable is True

    def test_pytorch_cuda_never_guessed_true_without_confirmed_readiness(self):
        # No NVIDIA hardware/driver evidence in this runner - a CUDA
        # build being installed must never be reported usable=True
        # without select_pytorch_backend() confirming readiness first
        # (torch.cuda.is_available() is never called to check this).
        payload = json.dumps({"version": "2.5.1+cu124", "cuda": "12.4", "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        report = build_ai_capabilities(runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["pytorch_cuda"].usable is not True

    def test_pytorch_cuda_usable_true_only_when_decision_confirms_ready(
        self, tmp_path, monkeypatch
    ):
        import serein.ai.capabilities as caps_mod

        monkeypatch.setattr(
            caps_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            caps_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        payload = json.dumps({"version": "2.5.1+cu124", "cuda": "12.4", "hip": None})
        runner = FakeCommandRunner({
            "python3": _ok("python3", payload),
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["pytorch_cuda"].usable is True

    def test_pytorch_cuda_usable_false_when_installed_but_driver_missing(
        self, tmp_path, monkeypatch
    ):
        import serein.ai.capabilities as caps_mod

        monkeypatch.setattr(
            caps_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            caps_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        payload = json.dumps({"version": "2.5.1+cu124", "cuda": "12.4", "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["pytorch_cuda"].usable is False

    def test_to_dict_is_json_serializable(self):
        report = build_ai_capabilities(runner=FakeCommandRunner({}))
        assert json.dumps(report.to_dict())

    # --- NVIDIA AI container usability matrix (S4R Section 25/26/29/50) --

    def _nvidia_backend_monkeypatch(self, monkeypatch):
        import serein.ai.capabilities as caps_mod

        monkeypatch.setattr(
            caps_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            caps_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )

    def test_ai_container_usable_false_engine_only(self, tmp_path, monkeypatch):
        self._nvidia_backend_monkeypatch(monkeypatch)
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.0.0")})
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["ai_container_runtime"].usable is False

    def test_ai_container_usable_false_engine_and_toolkit_no_driver(self, tmp_path, monkeypatch):
        self._nvidia_backend_monkeypatch(monkeypatch)
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.0.0"),
            "nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0"),
        })
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["ai_container_runtime"].usable is False

    def test_ai_container_usable_false_driver_engine_toolkit_no_cdi(self, tmp_path, monkeypatch):
        self._nvidia_backend_monkeypatch(monkeypatch)
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.0.0"),
            "nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0"),
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["ai_container_runtime"].usable is False

    def test_ai_container_usable_true_full_chain(self, tmp_path, monkeypatch):
        self._nvidia_backend_monkeypatch(monkeypatch)
        (tmp_path / "etc" / "cdi").mkdir(parents=True)
        (tmp_path / "etc" / "cdi" / "nvidia.yaml").write_text("")
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.0.0"),
            "nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0"),
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["ai_container_runtime"].usable is True

    def test_ai_container_usable_true_via_cdi_list_evidence(self, tmp_path, monkeypatch):
        # CDI evidence via the read-only `nvidia-ctk cdi list` query
        # instead of a static spec file (S4R Section 27/28).
        self._nvidia_backend_monkeypatch(monkeypatch)

        class _Runner(FakeCommandRunner):
            def run(self, args, timeout=3.0):
                if args[:3] == ["nvidia-ctk", "cdi", "list"]:
                    return CommandResult(0, "nvidia.com/gpu=all\n", "")
                return super().run(args, timeout)

        runner = _Runner({
            "podman": _ok("podman", "podman version 5.0.0"),
            "nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0"),
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        report = build_ai_capabilities(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["ai_container_runtime"].usable is True


class TestForbiddenActions:
    """Section 99/100/115/119's quality bar, enforced as a direct
    regression across a range of plan states."""

    def _all_plans(self):
        scenarios = [
            FakeCommandRunner({}),
            FakeCommandRunner({
                "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
                "ollama": _ok("ollama", "ollama version is 0.4.1"),
                "podman": _ok("podman", "podman version 5.0.0"),
                "python3": _ok("python3", "1.0.0"),
            }),
        ]
        return [build_ai_plan(runner=r) for r in scenarios]

    def test_no_sudo_pip(self):
        # Checks the executable-facing fields only (action/verification/
        # target) - `reason` prose is allowed to *name* the forbidden
        # pattern to explain why it's avoided (e.g. "never `sudo pip
        # install torch`"), which is not the same as recommending it.
        for plan in self._all_plans():
            for action in plan.actions:
                blob = " ".join(
                    str(v) for v in (action.action, action.verification, action.target) if v
                )
                assert "sudo pip" not in blob
                assert "sudo -H pip" not in blob
                assert "pip install --system" not in blob

    def test_no_run_installer_recommended(self):
        for plan in self._all_plans():
            for action in plan.actions:
                fields = (action.action, action.verification, action.reason, action.target)
                blob = " ".join(str(v) for v in fields if v)
                assert "NVIDIA-Linux" not in blob
                assert ".run" not in blob

    def test_no_apply_action_type_anywhere(self):
        for plan in self._all_plans():
            for action in plan.actions:
                assert action.action != "apply"

    def test_no_trust_remote_code_mentioned_as_enabled(self):
        for plan in self._all_plans():
            for action in plan.actions:
                assert "trust_remote_code=True" not in (action.reason or "")

    def test_no_model_download_actions(self):
        for plan in self._all_plans():
            for action in plan.actions:
                blob = f"{action.action} {action.tool}".lower()
                assert "pull" not in blob
                assert "download" not in blob or "downloaded" not in blob


class TestPrivacy:
    def test_status_output_has_no_home_path_or_username(self, tmp_path, monkeypatch):
        import getpass
        import socket

        from serein.ai.status import build_ai_status

        monkeypatch.setenv("USER", "should-not-appear")
        status = build_ai_status(root=tmp_path, runner=FakeCommandRunner({}))
        blob = json.dumps(
            {
                "backend": status.backend.primary,
                "storage_hf_home": status.storage.hf_home,
                "storage_ollama": status.storage.ollama_models,
            }
        )
        assert socket.gethostname() not in blob
        assert getpass.getuser() not in blob

    def test_plan_never_contains_tmp_path(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        blob = json.dumps(plan.to_dict())
        assert str(tmp_path) not in blob

    def test_capabilities_never_contains_tmp_path(self, tmp_path):
        report = build_ai_capabilities(root=tmp_path, runner=FakeCommandRunner({}))
        blob = json.dumps(report.to_dict())
        assert str(tmp_path) not in blob


class TestPlanner:
    def _actions_by_id(self, plan):
        return {a.id: a for a in plan.actions}

    def test_deterministic(self, tmp_path):
        runner = FakeCommandRunner({})
        first = build_ai_plan(root=tmp_path, runner=runner).to_dict()
        second = build_ai_plan(root=tmp_path, runner=runner).to_dict()
        assert first == second

    def test_unknown_component_raises(self):
        with pytest.raises(ValueError):
            build_ai_plan("not-a-real-component")

    def test_component_filter(self, tmp_path):
        plan = build_ai_plan("inference", root=tmp_path, runner=FakeCommandRunner({}))
        assert plan.actions
        assert all(a.component == "inference" for a in plan.actions)

    def test_all_components_valid(self, tmp_path):
        for component in VALID_COMPONENTS:
            plan = build_ai_plan(component, root=tmp_path, runner=FakeCommandRunner({}))
            assert plan.schema_version == AI_PLAN_SCHEMA_VERSION

    def test_driver_skip_without_nvidia_hardware(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["nvidia.driver"].status == "SKIP"

    def test_cuda_toolkit_skip_without_nvidia_hardware(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["nvidia.cuda_toolkit"].status == "SKIP"

    def test_rocm_skip_without_amd_hardware(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["amd.rocm"].status == "SKIP"

    def test_pytorch_apply_when_absent_targets_cpu_on_no_gpu(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["python.pytorch"].status == "APPLY"
        assert "cpu" in actions["python.pytorch"].target

    def test_pytorch_noop_when_installed(self, tmp_path):
        payload = json.dumps({"version": "2.5.1+cpu", "cuda": None, "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        plan = build_ai_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["python.pytorch"].status == "NOOP"

    def test_transformers_apply_when_all_missing(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["python.transformers_baseline"].status == "APPLY"

    def test_transformers_noop_when_all_present(self, tmp_path):
        runner = FakeCommandRunner({"python3": _ok("python3", "1.0.0")})
        plan = build_ai_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["python.transformers_baseline"].status == "NOOP"

    def test_ollama_apply_when_absent(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["inference.ollama"].status == "APPLY"

    def test_ollama_plan_never_claims_user_level_install(self, tmp_path):
        # S4R Section 36-39/51/52: the official installer is
        # system-level - requires_root must be true and risk must not
        # be "low" (the pre-corrective default).
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        ollama_action = actions["inference.ollama"]
        assert ollama_action.requires_root is True
        assert ollama_action.risk != "low"

    def test_ollama_noop_when_present(self, tmp_path):
        runner = FakeCommandRunner({"ollama": _ok("ollama", "ollama version is 0.4.1")})
        plan = build_ai_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["inference.ollama"].status == "NOOP"

    def test_llama_cpp_apply_when_absent(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["inference.llama_cpp"].status == "APPLY"

    def test_containers_apply_when_absent(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["containers.engine"].status == "APPLY"

    def test_containers_noop_when_present(self, tmp_path):
        runner = FakeCommandRunner({"podman": _ok("podman", "podman version 5.0.0")})
        plan = build_ai_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["containers.engine"].status == "NOOP"

    def test_nvidia_container_toolkit_skip_without_nvidia_backend(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["containers.nvidia_toolkit"].status == "SKIP"

    def test_nvidia_container_toolkit_blocked_when_driver_missing(self, tmp_path, monkeypatch):
        # S4R Section 30: do not plan the toolkit merely because an
        # NVIDIA backend candidate exists if the driver path is
        # unresolved - the toolkit would not be usable without it.
        import serein.ai.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            planner_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["containers.nvidia_toolkit"].status == "BLOCKED"

    def test_nvidia_container_toolkit_apply_when_driver_usable(self, tmp_path, monkeypatch):
        import serein.ai.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            planner_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        runner = FakeCommandRunner({
            "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
        })
        plan = build_ai_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["containers.nvidia_toolkit"].status == "APPLY"

    def test_containers_skip_when_nested_container(self, tmp_path, monkeypatch):
        import serein.ai.planner as planner_mod
        from serein.hardware.models import EnvironmentInfo

        monkeypatch.setattr(
            planner_mod, "detect_environment",
            lambda root: EnvironmentInfo(
                virtualization="container", is_wsl=False, is_container=True
            ),
        )
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["containers.engine"].status == "SKIP"

    def test_voice_action_always_present_and_noop(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["voice.workload_note"].status == "NOOP"

    def test_voice_component_filter(self, tmp_path):
        plan = build_ai_plan("voice", root=tmp_path, runner=FakeCommandRunner({}))
        assert len(plan.actions) == 1
        assert plan.actions[0].component == "voice"

    def test_cuda_toolkit_never_apply_by_default(self, tmp_path, monkeypatch):
        # S4R Section 21/22/23: local CUDA Toolkit is NOT a default
        # PyTorch prerequisite - prebuilt CUDA wheels bundle their own
        # userspace runtime. The action stays NOOP-as-optional whether
        # or not a driver is present.
        import serein.ai.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            planner_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["nvidia.driver"].status == "APPLY"
        assert actions["nvidia.cuda_toolkit"].status == "NOOP"
        assert actions["nvidia.cuda_toolkit"].action != "apply"

    def test_cuda_toolkit_noop_when_installed(self, tmp_path, monkeypatch):
        import serein.ai.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            planner_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        runner = FakeCommandRunner({"nvcc": _ok("nvcc", "release 12.6, V12.6.85")})
        plan = build_ai_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["nvidia.cuda_toolkit"].status == "NOOP"
        assert actions["nvidia.cuda_toolkit"].current == "installed"

    def test_rocm_blocked_when_support_unknown(self, tmp_path, monkeypatch):
        import serein.ai.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_gpus", lambda root: [GPUDevice(vendor="AMD", kind="discrete")]
        )
        monkeypatch.setattr(
            planner_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy([GPUClassification("AMD", "discrete", "high")]),
        )
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["amd.rocm"].status == "BLOCKED"

    def test_rocm_blocked_when_rocminfo_absent(self, tmp_path, monkeypatch):
        # ROCm support can only ever be confirmed by rocminfo actually
        # running; with rocminfo absent, support is unconditionally
        # unknown and Serein will not guess from vendor ID alone.
        import serein.ai.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_gpus", lambda root: [GPUDevice(vendor="AMD", kind="discrete")]
        )
        monkeypatch.setattr(
            planner_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy([GPUClassification("AMD", "discrete", "high")]),
        )
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        actions = self._actions_by_id(plan)
        assert actions["amd.rocm"].status == "BLOCKED"

    @pytest.mark.parametrize(
        "rocminfo_output",
        [
            "Agent 1\n  Device Type:             GPU\n",
            "Agent 1\n  Device Type:             CPU\n",
        ],
    )
    def test_rocm_noop_when_rocminfo_already_installed(
        self, tmp_path, monkeypatch, rocminfo_output
    ):
        # Already installed -> NOOP either way; an installed-but-
        # unsupported combination is the doctor's job to WARN about,
        # not something reinstalling ROCm would fix.
        import serein.ai.planner as planner_mod

        monkeypatch.setattr(
            planner_mod, "detect_gpus", lambda root: [GPUDevice(vendor="AMD", kind="discrete")]
        )
        monkeypatch.setattr(
            planner_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy([GPUClassification("AMD", "discrete", "high")]),
        )
        runner = FakeCommandRunner({"rocminfo": _ok("rocminfo", rocminfo_output)})
        plan = build_ai_plan(root=tmp_path, runner=runner)
        actions = self._actions_by_id(plan)
        assert actions["amd.rocm"].status == "NOOP"

    def test_capability_plan_consistency_cuda_toolkit(self, tmp_path, monkeypatch):
        """S2RM/S3-style invariant: capabilities and the planner must
        never disagree about whether the CUDA Toolkit is present."""
        import serein.ai.capabilities as caps_mod
        import serein.ai.planner as planner_mod

        def _gpus(root):
            return [GPUDevice(vendor="NVIDIA", kind="discrete")]

        def _policy(root, gpus):
            classifications = [GPUClassification("NVIDIA", "discrete", "high")]
            return _gpu_policy(classifications, nvidia_present=True)

        monkeypatch.setattr(caps_mod, "detect_gpus", _gpus)
        monkeypatch.setattr(caps_mod, "detect_gpu_policy", _policy)
        monkeypatch.setattr(planner_mod, "detect_gpus", _gpus)
        monkeypatch.setattr(planner_mod, "detect_gpu_policy", _policy)

        scenarios = [
            FakeCommandRunner({}),
            FakeCommandRunner({
                "nvidia-smi": _ok("nvidia-smi", "Driver Version: 580.65.06  CUDA Version: 13.0"),
                "nvcc": _ok("nvcc", "release 12.6, V12.6.85"),
            }),
        ]
        for runner in scenarios:
            report = build_ai_capabilities(root=tmp_path, runner=runner)
            plan = build_ai_plan(root=tmp_path, runner=runner)
            toolkit_cap = next(c for c in report.capabilities if c.id == "cuda_toolkit")
            toolkit_action = next(a for a in plan.actions if a.id == "nvidia.cuda_toolkit")
            # The toolkit is optional/never-APPLY by default (S4R
            # Section 21-23), so the planner's status is always NOOP
            # once hardware is present - but "installed" agreement is
            # what actually matters here: the action's `current` field
            # must agree with the capability's `installed` field.
            assert toolkit_action.status == "NOOP"
            if toolkit_cap.installed:
                assert toolkit_action.current == "installed"
            else:
                assert toolkit_action.current == "not installed (optional)"

    def test_to_dict_is_json_serializable(self, tmp_path):
        plan = build_ai_plan(root=tmp_path, runner=FakeCommandRunner({}))
        assert json.dumps(plan.to_dict())


class TestDoctor:
    def test_clean_host_all_pass_or_skip(self, tmp_path):
        report = run_ai_checks(root=tmp_path, runner=FakeCommandRunner({}))
        assert report.exit_code == 0
        assert all(c.status is not CheckStatus.FAIL for c in report.checks)

    def test_multiple_cuda_toolkit_dirs_warns(self, tmp_path):
        (tmp_path / "usr" / "local" / "cuda-12.4").mkdir(parents=True)
        (tmp_path / "usr" / "local" / "cuda-12.6").mkdir(parents=True)
        report = run_ai_checks(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_cuda_toolkit_conflict"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_rocm_unsupported_hardware_warns(self, tmp_path, monkeypatch):
        import serein.ai.doctor as doctor_mod

        monkeypatch.setattr(
            doctor_mod, "detect_gpus", lambda root: [GPUDevice(vendor="AMD", kind="discrete")]
        )
        monkeypatch.setattr(
            doctor_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy([GPUClassification("AMD", "discrete", "high")]),
        )
        runner = FakeCommandRunner({
            "rocminfo": _ok("rocminfo", "Agent 1\n  Device Type:             CPU\n"),
        })
        report = run_ai_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_rocm_unsupported_hardware"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_container_engine_conflict_warns(self, tmp_path):
        runner = FakeCommandRunner({
            "podman": _ok("podman", "podman version 5.0.0"),
            "docker": _ok("docker", "Docker version 27.0.0"),
        })
        report = run_ai_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_container_engine_conflict"].status is CheckStatus.WARN

    def test_no_gpu_no_ai_stack_is_pass_not_fail(self, tmp_path):
        report = run_ai_checks(root=tmp_path, runner=FakeCommandRunner({}))
        assert all(c.status is not CheckStatus.FAIL for c in report.checks)

    def test_stale_cuda_marker_warns(self, tmp_path):
        (tmp_path / "usr" / "local" / "cuda").mkdir(parents=True)
        report = run_ai_checks(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_cuda_toolkit_stale_marker"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_no_marker_warning_when_toolkit_confirmed_installed(self, tmp_path):
        (tmp_path / "usr" / "local" / "cuda").mkdir(parents=True)
        runner = FakeCommandRunner({"nvcc": _ok("nvcc", "release 12.6, V12.6.85")})
        report = run_ai_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_cuda_toolkit_stale_marker"].status is CheckStatus.PASS

    def test_nvidia_cdi_missing_warns(self, tmp_path):
        runner = FakeCommandRunner({
            "nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0"),
        })
        report = run_ai_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_nvidia_container_cdi_missing"].status is CheckStatus.WARN

    def test_nvidia_cdi_present_passes(self, tmp_path):
        (tmp_path / "etc" / "cdi").mkdir(parents=True)
        (tmp_path / "etc" / "cdi" / "nvidia.yaml").write_text("")
        runner = FakeCommandRunner({
            "nvidia-ctk": _ok("nvidia-ctk", "NVIDIA Container Toolkit 1.17.0"),
        })
        report = run_ai_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_nvidia_container_cdi_missing"].status is CheckStatus.PASS

    def test_pytorch_cuda_build_no_driver_warns(self, tmp_path):
        payload = json.dumps({"version": "2.5.1+cu124", "cuda": "12.4", "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        report = run_ai_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_pytorch_backend_mismatch"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_pytorch_cpu_build_with_accelerator_present_warns_not_fails(
        self, tmp_path, monkeypatch
    ):
        import serein.ai.doctor as doctor_mod

        monkeypatch.setattr(
            doctor_mod, "detect_gpus", lambda root: [GPUDevice(vendor="NVIDIA", kind="discrete")]
        )
        monkeypatch.setattr(
            doctor_mod, "detect_gpu_policy",
            lambda root, gpus: _gpu_policy(
                [GPUClassification("NVIDIA", "discrete", "high")], nvidia_present=True
            ),
        )
        payload = json.dumps({"version": "2.5.1+cpu", "cuda": None, "hip": None})
        runner = FakeCommandRunner({"python3": _ok("python3", payload)})
        report = run_ai_checks(root=tmp_path, runner=runner)
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_pytorch_backend_mismatch"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_pytorch_not_installed_is_pass(self, tmp_path):
        report = run_ai_checks(root=tmp_path, runner=FakeCommandRunner({}))
        by_id = {c.id: c for c in report.checks}
        assert by_id["ai_pytorch_backend_mismatch"].status is CheckStatus.PASS

    def test_json_shape_matches_shared_doctor_report(self, tmp_path):
        report = run_ai_checks(root=tmp_path, runner=FakeCommandRunner({}))
        data = report.to_dict()
        assert data["schema_version"] == 1
        assert set(data["summary"]) == {"PASS", "WARN", "FAIL", "SKIP"}
