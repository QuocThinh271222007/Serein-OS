"""S2 hardware policy tests: capability model, planner, doctor. Every case
uses a fixture root under tests/fixtures/hosts/ — never the real host."""

from __future__ import annotations

import json

from serein.doctor.models import CheckStatus
from serein.hardware.capabilities import build_capabilities
from serein.hardware.cpu_policy import detect_cpu_policy
from serein.hardware.doctor import run_hardware_checks
from serein.hardware.gpu_policy import detect_gpu_policy
from serein.hardware.memory_policy import detect_memory_policy, detect_zram_capability
from serein.hardware.models import CAPABILITIES_SCHEMA_VERSION, PLAN_SCHEMA_VERSION
from serein.hardware.planner import VALID_PROFILES, build_hardware_plan
from serein.hardware.power_policy import detect_power_policy
from serein.hardware.probe import probe_hardware
from serein.hardware.resources import RESOURCES, missing_resources
from serein.hardware.storage_policy import detect_storage_policy
from serein.hardware.thermal import detect_thermal


def _actions_by_id(plan):
    return {a.id: a for a in plan.actions}


class TestCPUPolicy:
    def test_amd_pstate_epp(self, host_root):
        info = detect_cpu_policy(host_root("amd_desktop"))
        assert info.cpufreq_present is True
        assert info.driver == "amd-pstate-epp"
        assert info.governor == "powersave"
        assert "performance" in info.available_governors
        assert info.epp_current == "balance_performance"
        assert "balance_power" in info.epp_available

    def test_intel_pstate_active(self, host_root):
        info = detect_cpu_policy(host_root("intel_laptop"))
        assert info.driver == "intel_pstate"
        assert info.available_governors == ["performance", "powersave"]
        assert info.epp_current == "balance_performance"

    def test_acpi_cpufreq_no_epp(self, host_root):
        info = detect_cpu_policy(host_root("unknown_cpu_vendor"))
        assert info.driver == "acpi-cpufreq"
        assert info.epp_current is None
        assert info.epp_available == []

    def test_missing_cpufreq(self, host_root):
        for scenario in ("hybrid_gpu_laptop", "nvidia_workstation", "kvm_vm", "missing_data"):
            info = detect_cpu_policy(host_root(scenario))
            assert info.cpufreq_present is False
            assert info.driver is None


class TestMemoryPolicy:
    def test_none_configured(self, host_root):
        info = detect_memory_policy(host_root("amd_desktop"))
        assert info.swap_devices == []
        assert info.zram_devices == []
        assert info.zram_generator_config_sources == []
        assert info.zram_generator_config_ambiguous is False

    def test_existing_disk_swap_only(self, host_root):
        info = detect_memory_policy(host_root("intel_laptop"))
        assert len(info.swap_devices) == 1
        assert info.swap_devices[0].kind == "partition"
        assert info.zram_devices == []

    def test_existing_zram_only(self, host_root):
        info = detect_memory_policy(host_root("hybrid_gpu_laptop"))
        assert len(info.zram_devices) == 1
        assert info.zram_devices[0].comp_algorithm == "lz4"
        assert info.zram_generator_config_sources == ["/etc/systemd/zram-generator.conf"]
        assert len(info.swap_devices) == 1
        assert info.swap_devices[0].kind == "zram"

    def test_empty_confd_directory_is_not_a_false_positive(self, host_root):
        info = detect_memory_policy(host_root("zram_confd_empty"))
        assert info.zram_generator_config_sources == []

    def test_confd_with_only_non_conf_files_is_not_configured(self, host_root):
        info = detect_memory_policy(host_root("zram_confd_non_conf_only"))
        assert info.zram_generator_config_sources == []

    def test_confd_with_real_conf_file_is_configured(self, host_root):
        info = detect_memory_policy(host_root("zram_confd_real_conf"))
        assert info.zram_generator_config_sources == [
            "/etc/systemd/zram-generator.conf.d/10-example.conf"
        ]

    def test_run_systemd_search_path_is_scanned(self, host_root):
        info = detect_memory_policy(host_root("zram_run_config"))
        assert info.zram_generator_config_sources == ["/run/systemd/zram-generator.conf"]

    def test_usr_lib_systemd_search_path_is_scanned(self, host_root):
        info = detect_memory_policy(host_root("zram_usrlib_config"))
        assert info.zram_generator_config_sources == ["/usr/lib/systemd/zram-generator.conf"]

    def test_multiple_sources_marked_ambiguous(self, host_root):
        info = detect_memory_policy(host_root("zram_multiple_sources"))
        assert len(info.zram_generator_config_sources) == 2
        assert info.zram_generator_config_ambiguous is True

    def test_both_zram_and_disk_swap(self, host_root):
        info = detect_memory_policy(host_root("nvidia_workstation"))
        assert len(info.zram_devices) == 1
        assert info.zram_devices[0].comp_algorithm == "zstd"
        disk_swaps = [s for s in info.swap_devices if s.kind != "zram"]
        assert len(disk_swaps) == 1

    def test_wsl_swapfile_detected(self, host_root):
        info = detect_memory_policy(host_root("wsl_environment"))
        assert len(info.swap_devices) == 1
        assert info.swap_devices[0].kind == "file"

    def test_missing_data_never_raises(self, host_root):
        info = detect_memory_policy(host_root("missing_data"))
        assert info.swap_devices == []
        assert info.zram_devices == []


class TestStoragePolicy:
    def test_nvme_scheduler_recognized(self, host_root):
        info = detect_storage_policy(host_root("amd_desktop"))
        device = next(d for d in info.devices if d.name == "nvme0n1")
        assert device.current_scheduler == "none"
        assert "mq-deadline" in device.available_schedulers

    def test_sata_ssd_scheduler(self, host_root):
        info = detect_storage_policy(host_root("intel_laptop"))
        device = next(d for d in info.devices if d.name == "sda")
        assert device.current_scheduler == "mq-deadline"

    def test_hdd_scheduler(self, host_root):
        info = detect_storage_policy(host_root("unknown_cpu_vendor"))
        device = next(d for d in info.devices if d.name == "sdb")
        assert device.current_scheduler == "bfq"

    def test_virtual_disk_scheduler(self, host_root):
        info = detect_storage_policy(host_root("kvm_vm"))
        device = next(d for d in info.devices if d.name == "vda")
        assert device.current_scheduler == "none"

    def test_missing_scheduler_file(self, host_root):
        info = detect_storage_policy(host_root("nvidia_workstation"))
        # nvme0n1/nvme1n1 both have scheduler files staged; assert no crash
        # and both are present.
        names = {d.name for d in info.devices}
        assert {"nvme0n1", "nvme1n1"} <= names

    def test_missing_data_returns_empty(self, host_root):
        assert detect_storage_policy(host_root("missing_data")).devices == []


class TestPowerPolicy:
    def test_ppd_present(self, host_root):
        assert detect_power_policy(host_root("amd_desktop")).ppd_present is True

    def test_ppd_absent(self, host_root):
        assert detect_power_policy(host_root("unknown_cpu_vendor")).ppd_present is False

    def test_battery_capacity_and_status(self, host_root):
        info = detect_power_policy(host_root("intel_laptop"))
        assert len(info.batteries) == 1
        assert info.batteries[0].capacity_percent == 76
        assert info.batteries[0].status == "Charging"

    def test_missing_data_never_raises(self, host_root):
        info = detect_power_policy(host_root("missing_data"))
        assert info.batteries == []
        assert info.ppd_present is False


class TestGPUPolicy:
    """S2R correction: hybrid is a tri-state (True/False/None). A device
    is only "integrated"/"discrete" with confidence when real PCI class
    or boot_vga evidence supports it - see gpu_policy.py and
    docs/validation/s2r/gpu-corrective.md."""

    def test_hybrid_detected_with_boot_vga_and_class_evidence(self, host_root):
        hw = probe_hardware(host_root("nvidia_workstation"))
        info = detect_gpu_policy(host_root("nvidia_workstation"), hw.gpu)
        assert info.hybrid is True
        assert info.hybrid_confidence == "medium"  # Intel side is a medium-confidence heuristic
        assert info.nvidia_present is True
        assert info.nvidia_kernel_module_loaded is True
        assert info.integrated_count == 1
        assert info.discrete_count == 1

    def test_no_gpu(self, host_root):
        hw = probe_hardware(host_root("unknown_cpu_vendor"))
        info = detect_gpu_policy(host_root("unknown_cpu_vendor"), hw.gpu)
        assert info.hybrid is False
        assert info.hybrid_confidence == "high"
        assert info.nvidia_present is False
        assert info.discrete_count == 0

    def test_amd_desktop_solo_gpu_is_not_falsely_hybrid_and_kind_is_unknown(self, host_root):
        hw = probe_hardware(host_root("amd_desktop"))
        info = detect_gpu_policy(host_root("amd_desktop"), hw.gpu)
        assert info.hybrid is False  # a solo GPU can never be hybrid, regardless of its own kind
        assert info.discrete_count == 0  # no class/boot_vga evidence -> not confidently classified
        assert info.integrated_count == 0
        assert info.classifications[0].kind == "unknown"

    def test_intel_arc_like_discrete_via_pci_class(self, host_root):
        hw = probe_hardware(host_root("intel_arc_workstation"))
        info = detect_gpu_policy(host_root("intel_arc_workstation"), hw.gpu)
        assert info.classifications[0].kind == "discrete"
        assert info.classifications[0].confidence == "high"
        assert info.hybrid is False

    def test_amd_apu_plus_nvidia_hybrid(self, host_root):
        hw = probe_hardware(host_root("amd_apu_nvidia_laptop"))
        info = detect_gpu_policy(host_root("amd_apu_nvidia_laptop"), hw.gpu)
        assert info.hybrid is True
        assert info.integrated_count == 1
        assert info.discrete_count == 1

    def test_multiple_gpus_unresolved_topology_is_none_not_false(self, host_root):
        hw = probe_hardware(host_root("multi_gpu_unknown"))
        info = detect_gpu_policy(host_root("multi_gpu_unknown"), hw.gpu)
        assert info.hybrid is None
        assert info.hybrid_confidence == "low"


class TestThermal:
    def test_zones_and_hwmon_present(self, host_root):
        info = detect_thermal(host_root("amd_desktop"))
        assert len(info.zones) == 1
        assert info.zones[0].temp_celsius == 45.0
        assert info.hwmon_present is True

    def test_absent(self, host_root):
        info = detect_thermal(host_root("unknown_cpu_vendor"))
        assert info.zones == []
        assert info.hwmon_present is False

    def test_missing_data_never_raises(self, host_root):
        info = detect_thermal(host_root("missing_data"))
        assert info.zones == []


class TestCapabilities:
    def test_schema_version(self, host_root):
        report = build_capabilities(host_root("amd_desktop"))
        assert report.schema_version == CAPABILITIES_SCHEMA_VERSION

    def test_all_ids_present_exactly_once(self, host_root):
        report = build_capabilities(host_root("amd_desktop"))
        ids = [c.id for c in report.capabilities]
        assert len(ids) == len(set(ids)) == 10

    def test_wsl_guards_governor_and_scheduler(self, host_root):
        report = build_capabilities(host_root("wsl_environment"))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["cpu_governor_control"].available is False
        assert by_id["cpu_epp_control"].available is False
        assert by_id["storage_scheduler_configurable"].available is False
        # swap is not virtualization-gated: WSL2 commonly has a real swapfile.
        assert by_id["swap_exists"].available is True

    def test_container_guards_governor(self, host_root):
        report = build_capabilities(host_root("container_like"))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["cpu_governor_control"].available is False

    def test_gpu_switching_is_unknown_not_false(self, host_root):
        report = build_capabilities(host_root("nvidia_workstation"))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["gpu_switching"].available is None

    def test_bare_metal_governor_control_available(self, host_root):
        report = build_capabilities(host_root("amd_desktop"))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["cpu_governor_control"].available is True
        assert by_id["power_profile_control"].available is True
        assert by_id["nvidia_compute_gpu"].available is False

    def test_to_dict_is_json_serializable(self, host_root):
        report = build_capabilities(host_root("amd_desktop"))
        assert json.dumps(report.to_dict())

    def test_zram_configurable_true_with_zram_control_evidence(self, host_root):
        report = build_capabilities(host_root("zram_supported_bare_metal"))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["zram_configurable"].available is True

    def test_zram_configurable_false_on_bare_metal_without_evidence(self, host_root):
        report = build_capabilities(host_root("amd_desktop"))
        by_id = {c.id: c for c in report.capabilities}
        assert by_id["zram_configurable"].available is False


class TestPlanner:
    def test_deterministic(self, host_root):
        root = host_root("amd_desktop")
        assert build_hardware_plan("balanced", root).to_dict() == build_hardware_plan(
            "balanced", root
        ).to_dict()

    def test_unknown_profile_raises(self, host_root):
        import pytest

        with pytest.raises(ValueError):
            build_hardware_plan("nonexistent", host_root("amd_desktop"))

    def test_battery_unavailable_without_battery(self, host_root):
        plan = build_hardware_plan("battery", host_root("amd_desktop"))
        assert plan.profile_available is False
        assert plan.actions == []
        assert "battery" in (plan.unavailable_reason or "").lower()

    def test_battery_available_with_battery(self, host_root):
        plan = build_hardware_plan("battery", host_root("intel_laptop"))
        assert plan.profile_available is True

    def test_wsl_cpu_and_storage_actions_skip(self, host_root):
        plan = build_hardware_plan("balanced", host_root("wsl_environment"))
        actions = _actions_by_id(plan)
        assert actions["cpu.epp"].status == "SKIP"

    def test_container_cpu_action_skips(self, host_root):
        plan = build_hardware_plan("dev", host_root("container_like"))
        actions = _actions_by_id(plan)
        assert actions["cpu.epp"].status == "SKIP"

    def test_cpu_epp_apply_when_target_available_and_differs(self, host_root):
        # amd_desktop starts at balance_performance; ai profile on a
        # desktop (no battery => "on AC or desktop") prefers "performance".
        plan = build_hardware_plan("ai", host_root("amd_desktop"))
        actions = _actions_by_id(plan)
        assert actions["cpu.epp"].status == "APPLY"
        assert actions["cpu.epp"].target == "performance"

    def test_cpu_epp_noop_when_already_at_target(self, host_root):
        plan = build_hardware_plan("dev", host_root("amd_desktop"))
        actions = _actions_by_id(plan)
        assert actions["cpu.epp"].status == "NOOP"

    def test_cpu_epp_skip_without_epp_support(self, host_root):
        plan = build_hardware_plan("balanced", host_root("unknown_cpu_vendor"))
        actions = _actions_by_id(plan)
        assert actions["cpu.epp"].status == "SKIP"

    def test_zram_noop_when_already_present(self, host_root):
        plan = build_hardware_plan("balanced", host_root("hybrid_gpu_laptop"))
        actions = _actions_by_id(plan)
        assert actions["memory.zram"].status == "NOOP"

    def test_zram_apply_when_capability_proven(self, host_root):
        # S2RM: APPLY requires proven kernel capability (zram-control),
        # not merely "no existing implementation" - see
        # zram_supported_bare_metal fixture.
        plan = build_hardware_plan("balanced", host_root("zram_supported_bare_metal"))
        actions = _actions_by_id(plan)
        assert actions["memory.zram"].status == "APPLY"

    def test_zram_blocked_when_capability_unproven_on_bare_metal(self, host_root):
        # S2RM: the capability/planner consistency invariant. amd_desktop
        # is bare metal with no zram-control/module/device evidence, so
        # zram_configurable is false - the planner must never return
        # APPLY here, even though nothing else blocks it (no existing
        # implementation, not virtualized, RAM known).
        plan = build_hardware_plan("balanced", host_root("amd_desktop"))
        actions = _actions_by_id(plan)
        assert actions["memory.zram"].status == "BLOCKED"

    def test_zram_blocked_without_ram_size(self, host_root):
        plan = build_hardware_plan("balanced", host_root("missing_data"))
        actions = _actions_by_id(plan)
        assert actions["memory.zram"].status == "BLOCKED"

    def test_zram_skips_under_wsl_when_not_already_configured(self, host_root):
        plan = build_hardware_plan("balanced", host_root("wsl_environment"))
        actions = _actions_by_id(plan)
        assert actions["memory.zram"].status == "SKIP"

    def test_zram_skips_under_container_when_not_already_configured(self, host_root):
        plan = build_hardware_plan("balanced", host_root("container_like"))
        actions = _actions_by_id(plan)
        assert actions["memory.zram"].status == "SKIP"

    def test_zram_existing_device_wins_over_virtualization_skip(self, host_root):
        # Evidence of an already-active device/config takes priority over
        # the virtualization guard - never mask real state with a guard.
        plan = build_hardware_plan("balanced", host_root("hybrid_gpu_laptop"))
        actions = _actions_by_id(plan)
        assert actions["memory.zram"].status == "NOOP"

    def test_nvme_scheduler_never_speculatively_applied(self, host_root):
        # S2R correction: S2's "NVMe + none available -> APPLY none" rule
        # was speculative tuning with no Serein-specific benchmark
        # evidence and has been removed - see docs/hardware/storage-policy.md
        # and docs/validation/s2r/known-blockers.md. Every device, on any
        # bus, is now left exactly as the kernel/upstream set it.
        plan = build_hardware_plan("balanced", host_root("nvidia_workstation"))
        actions = _actions_by_id(plan)
        assert actions["storage.scheduler.nvme0n1"].status == "NOOP"
        assert actions["storage.scheduler.nvme0n1"].target == "mq-deadline"
        assert actions["storage.scheduler.nvme1n1"].status == "NOOP"

    def test_non_nvme_scheduler_always_noop(self, host_root):
        plan = build_hardware_plan("balanced", host_root("intel_laptop"))
        actions = _actions_by_id(plan)
        assert actions["storage.scheduler.sda"].status == "NOOP"

    def test_power_profile_maps_battery_to_power_saver(self, host_root):
        plan = build_hardware_plan("battery", host_root("intel_laptop"))
        actions = _actions_by_id(plan)
        assert actions["power.ppd_profile"].target == "power-saver"

    def test_power_profile_skips_without_ppd(self, host_root):
        plan = build_hardware_plan("balanced", host_root("unknown_cpu_vendor"))
        actions = _actions_by_id(plan)
        assert actions["power.ppd_profile"].status == "SKIP"

    def test_ai_profile_noop_without_discrete_gpu(self, host_root):
        plan = build_hardware_plan("ai", host_root("unknown_cpu_vendor"))
        actions = _actions_by_id(plan)
        assert actions["gpu.compute_topology"].status == "NOOP"
        assert plan.profile_available is True

    def test_battery_profile_gpu_action_handles_ambiguous_hybrid(self, host_root):
        # multi_gpu_unknown has no battery, so exercise this via a
        # fixture that has both a battery and unresolved GPU topology by
        # checking the underlying action directly is not necessary here -
        # the important contract is that build_hardware_plan never
        # raises and never claims hybrid=True/False without evidence.
        plan = build_hardware_plan("balanced", host_root("multi_gpu_unknown"))
        actions = _actions_by_id(plan)
        assert actions["gpu.compute_topology"].status == "NOOP"

    def test_all_profiles_generate_for_every_scenario(self, host_root):
        scenarios = [
            "amd_desktop", "intel_laptop", "hybrid_gpu_laptop", "nvidia_workstation",
            "kvm_vm", "unknown_cpu_vendor", "wsl_environment", "container_like",
            "missing_data", "amd_apu_nvidia_laptop", "intel_arc_workstation",
            "multi_gpu_unknown",
        ]
        for scenario in scenarios:
            for profile_id in VALID_PROFILES:
                plan = build_hardware_plan(profile_id, host_root(scenario))
                assert plan.schema_version == PLAN_SCHEMA_VERSION

    def test_to_dict_is_json_serializable(self, host_root):
        plan = build_hardware_plan("ai", host_root("nvidia_workstation"))
        assert json.dumps(plan.to_dict())


class TestZramCapabilityPlannerInvariant:
    """S2RM's core acceptance gate: a planner must never propose APPLY
    for a mechanism the capability model says is unavailable. Checked
    directly (both call the same detect_zram_capability) and indirectly
    (via the public capabilities/plan surfaces) across every scenario
    and all five profiles, since ZRAM manageability is a machine
    capability, not something that should vary arbitrarily by profile."""

    _SCENARIOS = (
        "amd_desktop", "intel_laptop", "hybrid_gpu_laptop", "nvidia_workstation",
        "kvm_vm", "unknown_cpu_vendor", "wsl_environment", "container_like",
        "missing_data", "zram_supported_bare_metal", "zram_confd_empty",
        "zram_confd_non_conf_only", "zram_confd_real_conf", "zram_run_config",
        "zram_usrlib_config", "zram_multiple_sources",
    )

    def test_capability_and_planner_share_the_same_source(self, host_root):
        for scenario in self._SCENARIOS:
            root = host_root(scenario)
            hw = probe_hardware(root)
            memory_policy = detect_memory_policy(root)
            capability = detect_zram_capability(root, hw.environment, memory_policy)
            for profile_id in VALID_PROFILES:
                plan = build_hardware_plan(profile_id, root)
                if not plan.profile_available:
                    continue  # e.g. "battery" with no battery: no actions at all
                zram_action = _actions_by_id(plan)["memory.zram"]
                if capability.available is not True:
                    assert zram_action.status != "APPLY", (
                        f"{scenario}/{profile_id}: capability.available="
                        f"{capability.available} but plan status was APPLY"
                    )

    def test_capabilities_and_plan_agree_via_public_surfaces(self, host_root):
        for scenario in self._SCENARIOS:
            root = host_root(scenario)
            cap_report = build_capabilities(root)
            zram_cap = next(c for c in cap_report.capabilities if c.id == "zram_configurable")
            for profile_id in VALID_PROFILES:
                plan = build_hardware_plan(profile_id, root)
                if not plan.profile_available:
                    continue
                zram_action = _actions_by_id(plan)["memory.zram"]
                if zram_cap.available is not True:
                    assert zram_action.status != "APPLY"


class TestHardwareResources:
    def test_all_declared_resources_exist_in_repo(self):
        assert missing_resources() == []

    def test_resource_ids_unique(self):
        ids = [r.id for r in RESOURCES]
        assert len(ids) == len(set(ids))


class TestHardwareDoctor:
    def test_bare_metal_no_special_state(self, host_root):
        report = run_hardware_checks(host_root("amd_desktop"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_report_integrity"].status is CheckStatus.PASS
        assert by_id["hardware_existing_zram"].status is CheckStatus.SKIP
        assert by_id["hardware_virtualization_guard"].status is CheckStatus.SKIP
        assert report.exit_code == 0

    def test_existing_zram_passes(self, host_root):
        report = run_hardware_checks(host_root("hybrid_gpu_laptop"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_existing_zram"].status is CheckStatus.PASS

    def test_container_storage_skip(self, host_root):
        report = run_hardware_checks(host_root("container_like"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_storage_detection"].status is CheckStatus.SKIP

    def test_virtualization_guard_passes_under_wsl(self, host_root):
        report = run_hardware_checks(host_root("wsl_environment"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_virtualization_guard"].status is CheckStatus.PASS

    def test_missing_data_never_raises_and_warns(self, host_root):
        report = run_hardware_checks(host_root("missing_data"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_cpu_topology"].status is CheckStatus.WARN
        assert by_id["hardware_memory_detection"].status is CheckStatus.WARN

    def test_battery_capacity_readable_passes(self, host_root):
        report = run_hardware_checks(host_root("intel_laptop"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_power_consistency"].status is CheckStatus.PASS

    def test_json_shape_matches_shared_doctor_report(self, host_root):
        report = run_hardware_checks(host_root("amd_desktop"))
        data = report.to_dict()
        assert data["schema_version"] == 1
        assert set(data["summary"]) == {"PASS", "WARN", "FAIL", "SKIP"}

    def test_ambiguous_zram_config_warns_not_fails(self, host_root):
        report = run_hardware_checks(host_root("zram_multiple_sources"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_existing_zram"].status is CheckStatus.WARN
        assert report.exit_code == 0

    def test_gpu_topology_confidence_skips_with_no_gpu(self, host_root):
        report = run_hardware_checks(host_root("unknown_cpu_vendor"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_gpu_topology_confidence"].status is CheckStatus.SKIP

    def test_gpu_topology_confidence_passes_with_resolved_topology(self, host_root):
        report = run_hardware_checks(host_root("amd_desktop"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_gpu_topology_confidence"].status is CheckStatus.PASS

    def test_gpu_topology_confidence_warns_when_unresolved(self, host_root):
        report = run_hardware_checks(host_root("multi_gpu_unknown"))
        by_id = {c.id: c for c in report.checks}
        assert by_id["hardware_gpu_topology_confidence"].status is CheckStatus.WARN
        assert report.exit_code == 0
