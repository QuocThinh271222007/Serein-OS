"""Hardware probe tests. Every case uses a fixture root under
tests/fixtures/hosts/ — never the real host, real /proc, or the network."""

from __future__ import annotations

from serein.hardware.cpu import read_cpu_info
from serein.hardware.environment import detect_environment
from serein.hardware.gpu import detect_gpus
from serein.hardware.kernel import read_kernel_info
from serein.hardware.memory import read_memory_info
from serein.hardware.models import SCHEMA_VERSION
from serein.hardware.os_release import read_os_release
from serein.hardware.power import detect_power
from serein.hardware.probe import probe_hardware
from serein.hardware.storage import detect_storage


class TestOSRelease:
    def test_parses_ubuntu(self, host_root):
        info = read_os_release(host_root("amd_desktop"))
        assert info.id == "ubuntu"
        assert info.is_ubuntu is True
        assert info.version_id == "26.04"
        assert info.id_like == ["debian"]
        assert info.pretty_name == "Ubuntu 26.04 LTS"

    def test_missing_file_returns_empty(self, host_root):
        info = read_os_release(host_root("missing_data"))
        assert info.id is None
        assert info.is_ubuntu is False
        assert info.id_like == []


class TestKernel:
    def test_reads_from_proc(self, host_root):
        info = read_kernel_info(host_root("amd_desktop"))
        assert info.release is not None
        assert "6.14" in info.version

    def test_missing_data_stays_none(self, host_root):
        info = read_kernel_info(host_root("missing_data"))
        assert info.name is None
        assert info.release is None
        assert info.version is None


class TestCPU:
    def test_amd_desktop_physical_and_logical_cores(self, host_root):
        info = read_cpu_info(host_root("amd_desktop"))
        assert info.vendor == "AMD"
        assert info.logical_cores == 12
        assert info.physical_cores == 6
        assert "Ryzen" in info.model_name

    def test_intel_laptop(self, host_root):
        info = read_cpu_info(host_root("intel_laptop"))
        assert info.vendor == "Intel"
        assert info.logical_cores == 4
        assert info.physical_cores == 4

    def test_missing_data_stays_none(self, host_root):
        info = read_cpu_info(host_root("missing_data"))
        assert info.vendor is None
        assert info.model_name is None
        assert info.logical_cores is None


class TestMemory:
    def test_amd_desktop_32gib(self, host_root):
        info = read_memory_info(host_root("amd_desktop"))
        assert info.total_bytes == 33554432 * 1024
        assert info.available_bytes == 30000000 * 1024

    def test_missing_data_stays_none(self, host_root):
        info = read_memory_info(host_root("missing_data"))
        assert info.total_bytes is None
        assert info.available_bytes is None


class TestGPU:
    def test_amd_desktop_single_discrete_amd_gpu(self, host_root):
        gpus = detect_gpus(host_root("amd_desktop"))
        assert len(gpus) == 1
        assert gpus[0].vendor == "AMD"
        assert gpus[0].kind == "discrete"

    def test_intel_laptop_single_integrated_gpu(self, host_root):
        gpus = detect_gpus(host_root("intel_laptop"))
        assert len(gpus) == 1
        assert gpus[0].vendor == "Intel"
        assert gpus[0].kind == "integrated"

    def test_nvidia_workstation_hybrid_multi_gpu(self, host_root):
        gpus = detect_gpus(host_root("nvidia_workstation"))
        vendors = {(gpu.vendor, gpu.kind) for gpu in gpus}
        assert vendors == {("Intel", "integrated"), ("NVIDIA", "discrete")}

    def test_hybrid_gpu_laptop_multi_gpu(self, host_root):
        gpus = detect_gpus(host_root("hybrid_gpu_laptop"))
        vendors = {(gpu.vendor, gpu.kind) for gpu in gpus}
        assert vendors == {("Intel", "integrated"), ("AMD", "discrete")}

    def test_missing_data_returns_empty_list_not_error(self, host_root):
        assert detect_gpus(host_root("missing_data")) == []

    def test_wsl_has_no_gpu_nodes(self, host_root):
        assert detect_gpus(host_root("wsl_environment")) == []


class TestStorage:
    def test_amd_desktop_nvme(self, host_root):
        devices = detect_storage(host_root("amd_desktop"))
        assert len(devices) == 1
        assert devices[0].name == "nvme0n1"
        assert devices[0].device_class == "nvme"
        assert devices[0].size_bytes == 1953525168 * 512

    def test_intel_laptop_sata_ssd(self, host_root):
        devices = detect_storage(host_root("intel_laptop"))
        assert len(devices) == 1
        assert devices[0].device_class == "ssd"

    def test_nvidia_workstation_multiple_nvme(self, host_root):
        devices = detect_storage(host_root("nvidia_workstation"))
        assert {d.name for d in devices} == {"nvme0n1", "nvme1n1"}
        assert all(d.device_class == "nvme" for d in devices)

    def test_missing_data_returns_empty_list(self, host_root):
        assert detect_storage(host_root("missing_data")) == []


class TestPower:
    def test_desktop_has_no_battery(self, host_root):
        power = detect_power(host_root("amd_desktop"))
        assert power.has_battery is False
        assert power.battery_count == 0
        assert power.on_ac_power is None

    def test_laptop_has_battery_and_ac(self, host_root):
        power = detect_power(host_root("intel_laptop"))
        assert power.has_battery is True
        assert power.battery_count == 1
        assert power.on_ac_power is True

    def test_missing_data_reports_no_battery_not_error(self, host_root):
        power = detect_power(host_root("missing_data"))
        assert power.has_battery is False
        assert power.on_ac_power is None


class TestEnvironment:
    def test_desktop_is_bare_metal(self, host_root):
        env = detect_environment(host_root("amd_desktop"))
        assert env.virtualization == "none"
        assert env.is_wsl is False
        assert env.is_container is False

    def test_wsl_detected(self, host_root):
        env = detect_environment(host_root("wsl_environment"))
        assert env.is_wsl is True
        assert env.virtualization == "wsl"

    def test_container_detected(self, host_root):
        env = detect_environment(host_root("container_like"))
        assert env.is_container is True
        assert env.virtualization == "container"

    def test_kvm_detected_via_dmi(self, host_root):
        env = detect_environment(host_root("kvm_vm"))
        assert env.virtualization == "kvm"

    def test_missing_data_reports_none(self, host_root):
        env = detect_environment(host_root("missing_data"))
        assert env.virtualization == "none"


class TestFullProbe:
    def test_schema_version_present(self, host_root):
        report = probe_hardware(host_root("amd_desktop"))
        assert report.schema_version == SCHEMA_VERSION

    def test_missing_data_never_raises(self, host_root):
        report = probe_hardware(host_root("missing_data"))
        assert report.gpu == []
        assert report.storage == []
        assert report.cpu.vendor is None

    def test_to_dict_is_json_serializable(self, host_root):
        import json

        report = probe_hardware(host_root("nvidia_workstation"))
        serialized = json.dumps(report.to_dict())
        assert "schema_version" in serialized

    def test_every_scenario_probes_without_raising(self, host_root):
        scenarios = [
            "amd_desktop",
            "intel_laptop",
            "nvidia_workstation",
            "hybrid_gpu_laptop",
            "wsl_environment",
            "container_like",
            "kvm_vm",
            "missing_data",
        ]
        for scenario in scenarios:
            report = probe_hardware(host_root(scenario))
            assert report.schema_version == SCHEMA_VERSION
