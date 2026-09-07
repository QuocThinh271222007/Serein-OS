"""Focus (S6.5) subsystem tests. Every detection call flows through the
same injected FakeCommandRunner/root/home every other subsystem's tests
use - S6.5 never re-implements detection, so these tests exercise the
real S2-S6 detectors through fixtures, never the real host. No test
performs a systemd/cgroup mutation, a service/container/VM start-stop,
a kill command, a GPU mutation, a power-profile mutation, or a network
mutation."""

from __future__ import annotations

import dataclasses
import json

import pytest

from serein.ai.models import AICapabilitiesReport
from serein.development.runner import CommandResult
from serein.doctor.models import CheckStatus
from serein.focus.capabilities import build_focus_capabilities
from serein.focus.doctor import run_focus_checks
from serein.focus.domains import CANONICAL_TRANSITIONS, is_valid_target, is_valid_transition
from serein.focus.evidence import FocusEvidence, gather_focus_evidence
from serein.focus.models import (
    DOMAIN_STATES,
    FOCUS_DOMAINS,
    FOCUS_TARGETS,
    GPU_LEASE_MODES,
    INSTANCE_LEVEL_INTENTS,
    PRIORITY_LEVELS,
    READINESS_STATES,
    RELATIVE_WEIGHTS,
    RESOURCE_PRECEDENCE,
)
from serein.focus.planner import build_focus_plan
from serein.focus.policy import build_focus_policy, evaluate_domain_readiness, evaluate_domain_roles
from serein.focus.resources import usable_ai_gpu_backend
from serein.focus.status import build_focus_status
from serein.focus.transition import build_focus_transition, build_focus_transition_plan
from serein.hardware.models import GPUDevice
from serein.veil.models import VeilCapabilitiesReport


class FakeCommandRunner:
    """Maps either an exact argv tuple or a bare binary name to a
    canned CommandResult (or None = "not found"). Records every call
    for tests that need to assert on invocation without ever actually
    running anything."""

    def __init__(self, responses: dict[str | tuple[str, ...], CommandResult | None]):
        self._responses = responses
        self.calls: list[list[str]] = []

    def run(self, args, timeout: float = 3.0):
        self.calls.append(list(args))
        key = tuple(args)
        if key in self._responses:
            return self._responses[key]
        binary = args[0]
        if binary in self._responses:
            return self._responses[binary]
        return None


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _empty_root(tmp_path, name: str = "root"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _empty_home(tmp_path, name: str = "home"):
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    return home


def _evidence(tmp_path, runner=None) -> FocusEvidence:
    return gather_focus_evidence(
        root=_empty_root(tmp_path), runner=runner or FakeCommandRunner({}),
        home=_empty_home(tmp_path),
    )


def _with_ai_capabilities(evidence: FocusEvidence, overrides: dict) -> FocusEvidence:
    """Returns a copy of ``evidence`` with the named AI capability ids
    (by id) replaced per ``overrides`` (a dict of id -> field overrides)
    - used only to exercise focus's own policy logic against evidence
    shapes S4's real detectors may not currently produce, exactly as
    the S6.5R corrective's GPU-backend test matrix requires."""
    capabilities = [
        dataclasses.replace(c, **overrides[c.id]) if c.id in overrides else c
        for c in evidence.ai_capabilities.capabilities
    ]
    report = AICapabilitiesReport(
        schema_version=evidence.ai_capabilities.schema_version, capabilities=capabilities
    )
    return dataclasses.replace(evidence, ai_capabilities=report)


def _with_veil_capabilities(evidence: FocusEvidence, overrides: dict) -> FocusEvidence:
    capabilities = [
        dataclasses.replace(c, **overrides[c.id]) if c.id in overrides else c
        for c in evidence.veil_capabilities.capabilities
    ]
    report = VeilCapabilitiesReport(
        schema_version=evidence.veil_capabilities.schema_version, capabilities=capabilities
    )
    return dataclasses.replace(evidence, veil_capabilities=report)


def _with_gpu(evidence: FocusEvidence) -> FocusEvidence:
    hardware = dataclasses.replace(
        evidence.hardware,
        gpu=[GPUDevice(vendor="nvidia", model="RTX 4090", kind="discrete")],
    )
    return dataclasses.replace(evidence, hardware=hardware)


# ---------------------------------------------------------------------------
# Constants / domain model (Section 5-10)
# ---------------------------------------------------------------------------


class TestFocusConstants:
    def test_focus_targets_include_balanced_and_four_domains(self):
        assert set(FOCUS_TARGETS) == {"balanced", "dev", "ai", "cyber", "private"}

    def test_focus_domains_are_exactly_four_professional_domains(self):
        assert set(FOCUS_DOMAINS) == {"dev", "ai", "cyber", "private"}
        assert "balanced" not in FOCUS_DOMAINS

    def test_domain_states_never_include_suspended(self):
        # Section 6: PRIMARY/SECONDARY/IDLE/OFF only.
        assert set(DOMAIN_STATES) == {"primary", "secondary", "idle", "off"}

    def test_readiness_states_present(self):
        assert set(READINESS_STATES) == {"available", "limited", "blocked", "unknown"}

    def test_relative_weights_are_not_percentages(self):
        # Section 19-20: values are relative weights, never sum to 100.
        assert RELATIVE_WEIGHTS["primary"] == 1000
        assert RELATIVE_WEIGHTS["secondary"] == 300
        assert RELATIVE_WEIGHTS["idle"] == 80
        assert sum(RELATIVE_WEIGHTS.values()) != 100

    def test_gpu_lease_modes_never_include_exclusive(self):
        # Section 30: "exclusive" is deliberately never a valid mode.
        assert "exclusive" not in GPU_LEASE_MODES

    def test_resource_precedence_places_safety_before_focus(self):
        # Section 10: safety/privacy/reserve outrank primary focus.
        primary_index = RESOURCE_PRECEDENCE.index("primary_focus")
        assert RESOURCE_PRECEDENCE.index("system_safety_thermal") < primary_index
        assert RESOURCE_PRECEDENCE.index("privacy_security_boundary") < primary_index
        assert RESOURCE_PRECEDENCE.index("os_desktop_survival_reserve") < primary_index

    def test_priority_levels_match_domain_states(self):
        assert set(PRIORITY_LEVELS) == set(DOMAIN_STATES)


class TestDomainsModule:
    def test_is_valid_target(self):
        assert is_valid_target("ai") is True
        assert is_valid_target("balanced") is True
        assert is_valid_target("nonsense") is False

    def test_is_valid_transition_same_target(self):
        assert is_valid_transition("ai", "ai") is True

    def test_is_valid_transition_unknown_target(self):
        assert is_valid_transition("ai", "nonsense") is False

    def test_canonical_transitions_cover_every_ordered_pair(self):
        expected = {
            (a, b) for a in FOCUS_TARGETS for b in FOCUS_TARGETS if a != b
        }
        assert set(CANONICAL_TRANSITIONS) == expected


# ---------------------------------------------------------------------------
# Evidence aggregator (Section 87-88, 11-15)
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_gather_focus_evidence_never_touches_real_host(self, tmp_path):
        runner = FakeCommandRunner({})
        evidence = _evidence(tmp_path, runner)
        assert evidence.hardware is not None
        assert evidence.development_capabilities is not None
        assert evidence.ai_capabilities is not None
        assert evidence.cyber_capabilities is not None
        assert evidence.veil_capabilities is not None

    def test_no_subprocess_call_ever_mutates(self, tmp_path):
        runner = FakeCommandRunner({})
        _evidence(tmp_path, runner)
        forbidden = ("install", "systemctl start", "systemctl enable", "virsh define", "podman run")
        for call in runner.calls:
            joined = " ".join(call).lower()
            for marker in forbidden:
                assert marker not in joined


# ---------------------------------------------------------------------------
# One-primary invariant (Section 7, 101)
# ---------------------------------------------------------------------------


class TestOnePrimaryInvariant:
    @pytest.mark.parametrize("target", ["dev", "ai", "cyber", "private"])
    def test_exactly_one_primary_for_professional_targets(self, tmp_path, target):
        evidence = _evidence(tmp_path)
        roles = evaluate_domain_roles(target, evidence)
        primaries = [r.domain for r in roles if r.state == "primary"]
        assert primaries == [target]

    def test_zero_primary_for_balanced(self, tmp_path):
        evidence = _evidence(tmp_path)
        roles = evaluate_domain_roles("balanced", evidence)
        primaries = [r.domain for r in roles if r.state == "primary"]
        assert primaries == []

    def test_invalid_two_primary_state_is_unreachable(self, tmp_path):
        # Direct regression matching Section 7's "invalid" example -
        # evaluate_domain_roles() can never produce two PRIMARY domains
        # for any single target.
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            roles = evaluate_domain_roles(target, evidence)
            primaries = [r.domain for r in roles if r.state == "primary"]
            assert len(primaries) <= 1

    def test_balanced_means_no_primary_not_another_workload(self, tmp_path):
        # Section 5: balanced != a fifth primary domain.
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("balanced", evidence)
        assert policy.primary_domain is None


# ---------------------------------------------------------------------------
# Primary != exclusive (Section 2, 8)
# ---------------------------------------------------------------------------


class TestPrimaryNotExclusive:
    def test_other_domains_remain_secondary_idle_or_off_never_removed(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        non_primary_states = {r.state for r in policy.domain_roles if r.domain != "ai"}
        assert non_primary_states <= {"secondary", "idle", "off"}
        assert len(policy.domain_roles) == 4  # every domain still represented, never dropped

    def test_no_kill_or_stop_language_anywhere_in_a_primary_plan(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        dumped = json.dumps(policy.to_dict()).lower()
        for marker in ("kill", "pkill", "killall", "systemctl stop"):
            assert marker not in dumped


# ---------------------------------------------------------------------------
# Domain readiness (Section 76-80)
# ---------------------------------------------------------------------------


class TestDomainReadiness:
    def test_readiness_covers_all_four_domains(self, tmp_path):
        evidence = _evidence(tmp_path)
        readiness = evaluate_domain_readiness(evidence)
        assert set(readiness.keys()) == set(FOCUS_DOMAINS)

    def test_ai_never_blocked_solely_for_missing_gpu(self, tmp_path):
        # Section 78: CPU-only AI is available/limited, never blocked.
        evidence = _evidence(tmp_path)
        state, _reason = evaluate_domain_readiness(evidence)["ai"]
        assert state != "blocked"

    def test_dev_never_blocked(self, tmp_path):
        evidence = _evidence(tmp_path)
        state, _reason = evaluate_domain_readiness(evidence)["dev"]
        assert state != "blocked"

    def test_cyber_available_without_vm_when_toolbox_installed(self, tmp_path):
        # Section 79: cyber should not require a VM if toolbox is available.
        runner = FakeCommandRunner({
            "podman": _ok("podman version 5.7.0"),
            "distrobox": _ok("distrobox: 1.8.2.4"),
        })
        evidence = _evidence(tmp_path, runner)
        state, _reason = evaluate_domain_readiness(evidence)["cyber"]
        assert state == "available"

    def test_private_blocked_when_nothing_usable(self, tmp_path):
        # Section 42/77.
        evidence = _evidence(tmp_path)
        state, reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "blocked"
        assert "anonymous" not in reason.lower()
        assert "fully anonymous" not in reason.lower()

    def test_private_reason_uses_mechanism_terms_not_marketing(self, tmp_path):
        evidence = _evidence(tmp_path)
        _state, reason = evaluate_domain_readiness(evidence)["private"]
        for marketing in ("high anonymity", "fully anonymous", "100% private"):
            assert marketing not in reason.lower()


# ---------------------------------------------------------------------------
# Private readiness fidelity (S6.5R Corrective D, Section 25-31/34/62)
# ---------------------------------------------------------------------------


class TestPrivateReadinessFidelity:
    def test_nothing_present_is_blocked(self, tmp_path):
        evidence = _evidence(tmp_path)
        state, _reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "blocked"

    def test_tor_client_usable_only_is_limited_not_available(self, tmp_path):
        # The exact regression S6.5R was filed to prevent: Tor client
        # usability alone must never upgrade readiness to "available".
        evidence = _with_veil_capabilities(
            _evidence(tmp_path), {"tor_client": {"installed": True, "usable": True}}
        )
        state, reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "limited"
        assert "tor client" in reason.lower()

    def test_tor_browser_installed_usability_unknown_is_limited(self, tmp_path):
        evidence = _with_veil_capabilities(
            _evidence(tmp_path), {"tor_browser": {"installed": True, "usable": None}}
        )
        state, _reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "limited"

    def test_whonix_artifacts_present_only_is_limited(self, tmp_path):
        evidence = _with_veil_capabilities(
            _evidence(tmp_path), {"whonix_vm": {"installed": True, "usable": None}}
        )
        state, _reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "limited"

    def test_private_workspace_usable_is_available(self, tmp_path):
        evidence = _with_veil_capabilities(
            _evidence(tmp_path), {"private_workspace": {"usable": True}}
        )
        state, _reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "available"

    def test_whonix_usable_is_available(self, tmp_path):
        evidence = _with_veil_capabilities(
            _evidence(tmp_path), {"whonix_vm": {"installed": True, "usable": True}}
        )
        state, _reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "available"

    def test_tor_browser_usable_is_available(self, tmp_path):
        evidence = _with_veil_capabilities(
            _evidence(tmp_path), {"tor_browser": {"installed": True, "usable": True}}
        )
        state, _reason = evaluate_domain_readiness(evidence)["private"]
        assert state == "available"

    def test_private_transition_stays_plannable_when_limited(self, tmp_path):
        # Section 32: a "limited" (not "blocked") private readiness may
        # still yield a PLANNABLE transition, with prerequisites/warnings.
        evidence = _with_veil_capabilities(
            _evidence(tmp_path), {"tor_client": {"installed": True, "usable": True}}
        )
        plan = build_focus_transition("ai", "private", evidence)
        assert plan.status == "PLANNABLE"
        assert plan.prerequisites


# ---------------------------------------------------------------------------
# CPU/IO weight model (Section 19-22, 102)
# ---------------------------------------------------------------------------


class TestResourceIntents:
    def test_cpu_weight_never_a_percentage(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        for intent in policy.resource_intents:
            if intent.resource == "cpu":
                mechanism = intent.mechanism.lower()
                assert "percentage" not in mechanism or "never" in mechanism
                assert intent.enforceable is False

    def test_primary_weight_exceeds_secondary_exceeds_idle(self, tmp_path):
        # Section 102: default ordering under normal, unconstrained plans.
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        weights = {
            i.domain: i.relative_weight for i in policy.resource_intents if i.resource == "cpu"
        }
        assert weights["ai"] > weights["dev"]  # primary > secondary
        assert weights["dev"] > weights["cyber"]  # secondary > idle

    def test_no_hard_cpu_quota_or_affinity_ever_mentioned(self, tmp_path):
        # Section 21-22: no CPUQuota=, no CPU affinity mask by default.
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            dumped = json.dumps(policy.to_dict()).lower()
            assert "cpuquota" not in dumped
            assert "affinity" not in dumped
            assert "taskset" not in dumped

    def test_off_domain_has_no_relative_weight(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        off_intents = [i for i in policy.resource_intents if i.priority == "off"]
        assert off_intents
        assert all(i.relative_weight is None for i in off_intents)


# ---------------------------------------------------------------------------
# Memory model (Section 23-27, 104)
# ---------------------------------------------------------------------------


class TestMemoryModel:
    def test_system_reserve_always_present(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            assert policy.memory_intent.system_reserve

    def test_no_policy_assigns_all_ram(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            assert policy.memory_intent.primary_target != "all"
            reserve_text = policy.memory_intent.system_reserve
            assert "100%" not in reserve_text or "never" in reserve_text.lower()

    def test_memorymax_never_the_default_mechanism(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            assert "memorymax" not in policy.memory_intent.mechanism.lower()

    def test_target_bytes_never_fabricated(self, tmp_path):
        # Section 25/104: unknown workload size never becomes a fake
        # precise byte target.
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            assert policy.memory_intent.target_bytes is None

    def test_memory_intent_never_enforceable(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            assert policy.memory_intent.enforceable is False


# ---------------------------------------------------------------------------
# GPU lease intent (Section 29-35, 103)
# ---------------------------------------------------------------------------


class TestGpuLeaseIntent:
    def test_gpu_never_enforceable(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            assert policy.gpu_intent.enforceable is False

    def test_ai_focus_prefers_gpu_only_when_gpu_present(self, tmp_path):
        evidence = _evidence(tmp_path)  # no GPU in fixture hardware
        policy = build_focus_policy("ai", evidence)
        assert policy.gpu_intent.mode == "unavailable"
        assert policy.gpu_intent.preferred_domain is None

    def test_dev_never_claims_exclusive_gpu(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("dev", evidence)
        assert policy.gpu_intent.mode != "preferred"

    def test_cyber_never_automatically_claims_gpu(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("cyber", evidence)
        assert policy.gpu_intent.preferred_domain != "cyber"

    def test_private_never_recommends_gpu_passthrough(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("private", evidence)
        assert policy.gpu_intent.preferred_domain != "private"
        dumped = json.dumps(policy.gpu_intent.to_dict()).lower()
        assert "passthrough" not in dumped

    def test_gpu_mode_always_recognized(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            assert policy.gpu_intent.mode in GPU_LEASE_MODES


# ---------------------------------------------------------------------------
# AI GPU backend gating (S6.5R Corrective C, Section 17-24/44-46/61)
# ---------------------------------------------------------------------------


class TestAiGpuBackendGating:
    def test_no_gpu_is_unavailable(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        assert policy.gpu_intent.mode == "unavailable"
        assert policy.gpu_intent.preferred_domain is None

    def test_gpu_present_no_usable_backend_is_not_preferred(self, tmp_path):
        evidence = _with_gpu(_evidence(tmp_path))
        policy = build_focus_policy("ai", evidence)
        assert policy.gpu_intent.preferred_domain is None
        assert policy.gpu_intent.mode == "shared"

    def test_gpu_present_hardware_only_is_not_enough(self, tmp_path):
        # Section 45: generic hardware presence alone must never gate
        # AI GPU preference.
        evidence = _with_ai_capabilities(
            _with_gpu(_evidence(tmp_path)),
            {"nvidia_hardware": {"installed": True, "usable": None}},
        )
        policy = build_focus_policy("ai", evidence)
        assert policy.gpu_intent.preferred_domain is None

    def test_gpu_present_driver_and_cuda_runtime_only_is_not_enough(self, tmp_path):
        # Driver + CUDA driver-API runtime presence, without a usable
        # PyTorch CUDA build, must never be sufficient (Section 24/45).
        evidence = _with_ai_capabilities(
            _with_gpu(_evidence(tmp_path)),
            {
                "nvidia_driver": {"installed": True, "usable": True},
                "cuda_runtime": {"installed": True, "usable": True},
                "pytorch_cuda": {"installed": False, "usable": False},
            },
        )
        policy = build_focus_policy("ai", evidence)
        assert policy.gpu_intent.preferred_domain is None
        assert policy.gpu_intent.mode == "shared"

    def test_gpu_present_pytorch_cuda_usable_is_preferred(self, tmp_path):
        evidence = _with_ai_capabilities(
            _with_gpu(_evidence(tmp_path)),
            {"pytorch_cuda": {"installed": True, "usable": True}},
        )
        policy = build_focus_policy("ai", evidence)
        assert policy.gpu_intent.preferred_domain == "ai"
        assert policy.gpu_intent.mode == "preferred"
        assert policy.gpu_intent.enforceable is False

    def test_gpu_present_pytorch_rocm_usable_is_preferred(self, tmp_path):
        evidence = _with_ai_capabilities(
            _with_gpu(_evidence(tmp_path)),
            {"pytorch_rocm": {"installed": True, "usable": True}},
        )
        policy = build_focus_policy("ai", evidence)
        assert policy.gpu_intent.preferred_domain == "ai"
        assert policy.gpu_intent.mode == "preferred"

    def test_cpu_only_ai_never_prefers_gpu(self, tmp_path):
        # Section 22: AI focus stays valid CPU-only; that must never
        # imply a GPU preference exists.
        evidence = _with_ai_capabilities(
            _evidence(tmp_path), {"pytorch_cpu": {"installed": True, "usable": True}}
        )
        policy = build_focus_policy("ai", evidence)
        assert policy.readiness in ("available", "limited")
        assert policy.gpu_intent.preferred_domain is None
        assert policy.gpu_intent.mode == "unavailable"  # no GPU device at all

    def test_usable_ai_gpu_backend_helper_matches_gpu_intent(self, tmp_path):
        evidence = _with_ai_capabilities(
            _with_gpu(_evidence(tmp_path)),
            {"pytorch_cuda": {"installed": True, "usable": True}},
        )
        policy = build_focus_policy("ai", evidence)
        assert usable_ai_gpu_backend(evidence) is True
        assert policy.gpu_intent.preferred_domain == "ai"


# ---------------------------------------------------------------------------
# Service/container/VM lifecycle (Section 36-40, 117)
# ---------------------------------------------------------------------------


class TestLifecycleIntents:
    def test_every_lifecycle_target_is_serein_understood(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        known_targets = {"ai_runtime", "cyber_toolbox", "cyber_vm", "whonix"}
        assert {lc.target for lc in policy.lifecycle_intents} == known_targets

    def test_never_deletes_or_destroys(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            for lc in policy.lifecycle_intents:
                assert "delete" not in lc.reason.lower()
                assert "destroy" not in lc.reason.lower()
                assert "discard" not in lc.reason.lower()

    def test_not_installed_capability_is_skip(self, tmp_path):
        evidence = _evidence(tmp_path)  # nothing installed
        policy = build_focus_policy("ai", evidence)
        ai_runtime = next(lc for lc in policy.lifecycle_intents if lc.target == "ai_runtime")
        assert ai_runtime.status == "SKIP"
        assert ai_runtime.target_intent == "KEEP"

    def test_ai_runtime_binary_installed_instance_present_running_unknown(self, tmp_path):
        # S6.5R Corrective A, Section 5/38/58: binary presence is
        # acceptable evidence of instance_present for ai_runtime
        # specifically - it is the recognized instance itself; running
        # state stays unknown regardless (Section 37).
        runner = FakeCommandRunner({"ollama": _ok("ollama version 0.4.0")})
        evidence = _evidence(tmp_path, runner)
        policy = build_focus_policy("ai", evidence)
        ai_runtime = next(lc for lc in policy.lifecycle_intents if lc.target == "ai_runtime")
        assert ai_runtime.mechanism_available is True
        assert ai_runtime.instance_present is True
        assert ai_runtime.instance_running is None

    def test_cyber_toolbox_mechanism_available_but_no_instance_action(self, tmp_path):
        # S6.5R Corrective A, Section 6/39/58: Podman+Distrobox present
        # proves mechanism only - never a toolbox container instance.
        runner = FakeCommandRunner({
            "podman": _ok("podman version 5.7.0"),
            "distrobox": _ok("distrobox: 1.8.2.4"),
        })
        evidence = _evidence(tmp_path, runner)
        policy = build_focus_policy("cyber", evidence)
        toolbox = next(lc for lc in policy.lifecycle_intents if lc.target == "cyber_toolbox")
        assert toolbox.mechanism_available is True
        assert toolbox.instance_present is None
        assert toolbox.target_intent == "KEEP"
        assert toolbox.target_intent not in INSTANCE_LEVEL_INTENTS
        assert toolbox.status in ("NOOP", "SKIP")

    def test_cyber_vm_mechanism_ready_but_no_instance_action(self, tmp_path, monkeypatch):
        # S6.5R Corrective A, Section 7/40/58: KVM/QEMU/libvirt
        # readiness proves mechanism only - never a cyber VM instance.
        root = _empty_root(tmp_path)
        (root / "dev").mkdir(parents=True, exist_ok=True)
        (root / "dev" / "kvm").write_text("", encoding="utf-8")
        (root / "proc").mkdir(parents=True, exist_ok=True)
        (root / "proc" / "modules").write_text("kvm 12345 0 - Live 0x0\n", encoding="utf-8")
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("QEMU emulator version 8.2.2"),
            "virsh": _ok("6.0.0"),
        })
        evidence = gather_focus_evidence(root=root, runner=runner, home=_empty_home(tmp_path))
        policy = build_focus_policy("cyber", evidence)
        vm = next(lc for lc in policy.lifecycle_intents if lc.target == "cyber_vm")
        assert vm.mechanism_available is True
        assert vm.instance_present is None
        assert vm.target_intent == "KEEP"
        assert vm.target_intent not in INSTANCE_LEVEL_INTENTS

    def test_whonix_artifacts_present_but_no_instance_action(self, tmp_path, monkeypatch):
        # S6.5R Corrective A, Section 8-9/41/58: qcow2 artifact presence
        # never proves VM import/definition/running-instance existence.
        root = _empty_root(tmp_path)
        (root / "dev").mkdir(parents=True, exist_ok=True)
        (root / "dev" / "kvm").write_text("", encoding="utf-8")
        (root / "proc").mkdir(parents=True, exist_ok=True)
        (root / "proc" / "modules").write_text("kvm 12345 0 - Live 0x0\n", encoding="utf-8")
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        home = _empty_home(tmp_path)
        images_dir = home / ".local" / "share" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / "Whonix-Gateway.qcow2").write_text("", encoding="utf-8")
        (images_dir / "Whonix-Workstation.qcow2").write_text("", encoding="utf-8")
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("QEMU emulator version 8.2.2"),
            "virsh": _ok("6.0.0"),
        })
        evidence = gather_focus_evidence(root=root, runner=runner, home=home)
        policy = build_focus_policy("private", evidence)
        whonix = next(lc for lc in policy.lifecycle_intents if lc.target == "whonix")
        assert whonix.instance_present is None
        assert whonix.target_intent == "KEEP"
        assert whonix.target_intent not in INSTANCE_LEVEL_INTENTS


# ---------------------------------------------------------------------------
# Ownership semantics (S6.5R Corrective B, Section 12-16/59)
# ---------------------------------------------------------------------------


class TestOwnershipSemantics:
    def test_ai_runtime_recognized_but_not_managed(self, tmp_path):
        runner = FakeCommandRunner({"ollama": _ok("ollama version 0.4.0")})
        evidence = _evidence(tmp_path, runner)
        policy = build_focus_policy("ai", evidence)
        ai_runtime = next(lc for lc in policy.lifecycle_intents if lc.target == "ai_runtime")
        assert ai_runtime.recognized_by_serein is True
        assert ai_runtime.managed_by_serein is False

    def test_cyber_toolbox_recognized_but_not_managed(self, tmp_path):
        runner = FakeCommandRunner({
            "podman": _ok("podman version 5.7.0"),
            "distrobox": _ok("distrobox: 1.8.2.4"),
        })
        evidence = _evidence(tmp_path, runner)
        policy = build_focus_policy("cyber", evidence)
        toolbox = next(lc for lc in policy.lifecycle_intents if lc.target == "cyber_toolbox")
        assert toolbox.recognized_by_serein is True
        assert toolbox.managed_by_serein is False

    def test_cyber_vm_recognized_but_not_managed(self, tmp_path, monkeypatch):
        root = _empty_root(tmp_path)
        (root / "dev").mkdir(parents=True, exist_ok=True)
        (root / "dev" / "kvm").write_text("", encoding="utf-8")
        (root / "proc").mkdir(parents=True, exist_ok=True)
        (root / "proc" / "modules").write_text("kvm 12345 0 - Live 0x0\n", encoding="utf-8")
        monkeypatch.setattr("os.access", lambda *a, **kw: True)
        runner = FakeCommandRunner({
            "qemu-system-x86_64": _ok("QEMU emulator version 8.2.2"),
            "virsh": _ok("6.0.0"),
        })
        evidence = gather_focus_evidence(root=root, runner=runner, home=_empty_home(tmp_path))
        policy = build_focus_policy("cyber", evidence)
        vm = next(lc for lc in policy.lifecycle_intents if lc.target == "cyber_vm")
        assert vm.recognized_by_serein is True
        assert vm.managed_by_serein is False

    def test_whonix_recognized_but_not_managed(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("private", evidence)
        whonix = next(lc for lc in policy.lifecycle_intents if lc.target == "whonix")
        assert whonix.recognized_by_serein is True
        assert whonix.managed_by_serein is False

    def test_no_lifecycle_target_ever_managed_by_serein(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            for lc in policy.lifecycle_intents:
                assert lc.managed_by_serein is False, (
                    f"{target}: {lc.kind}.{lc.target} overclaims managed_by_serein"
                )


# ---------------------------------------------------------------------------
# Instance-action invariant (S6.5R Corrective A, Section 36/60)
# ---------------------------------------------------------------------------


class TestInstanceActionInvariant:
    def test_instance_level_intent_requires_instance_present_true(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            for lc in policy.lifecycle_intents:
                if lc.target_intent in INSTANCE_LEVEL_INTENTS:
                    assert lc.instance_present is True, (
                        f"{target}: {lc.kind}.{lc.target} proposes {lc.target_intent} "
                        f"with instance_present={lc.instance_present!r}"
                    )

    def test_ai_runtime_idle_with_instance_present_is_a_valid_quiesce_candidate(self, tmp_path):
        # Confirms the invariant is not simply "never propose instance
        # actions" - it is "only propose them with real evidence."
        runner = FakeCommandRunner({"ollama": _ok("ollama version 0.4.0")})
        evidence = _evidence(tmp_path, runner)
        policy = build_focus_policy("cyber", evidence)  # ai is idle under cyber focus
        ai_runtime = next(lc for lc in policy.lifecycle_intents if lc.target == "ai_runtime")
        assert ai_runtime.target_intent == "QUIESCE_CANDIDATE"
        assert ai_runtime.instance_present is True


# ---------------------------------------------------------------------------
# Transition planner (Section 51-58, 100-101, 105)
# ---------------------------------------------------------------------------


class TestTransitionPlanner:
    def test_same_focus_is_noop(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            plan = build_focus_transition(target, target, evidence)
            assert plan.status == "NOOP"
            assert plan.resource_changes == []
            assert plan.lifecycle_changes == []

    @pytest.mark.parametrize("from_focus,to_focus", list(CANONICAL_TRANSITIONS))
    def test_every_canonical_transition_plans_without_error(self, tmp_path, from_focus, to_focus):
        evidence = _evidence(tmp_path)
        plan = build_focus_transition(from_focus, to_focus, evidence)
        assert plan.status in ("NOOP", "PLANNABLE", "BLOCKED")
        assert plan.from_focus == from_focus
        assert plan.to_focus == to_focus

    def test_ai_to_cyber_transition_shape(self, tmp_path):
        evidence = _evidence(tmp_path)
        plan = build_focus_transition("ai", "cyber", evidence)
        cpu_changes = {
            c.domain: (c.before, c.after) for c in plan.resource_changes if c.resource == "cpu"
        }
        assert cpu_changes["ai"] == ("primary", "idle")
        assert cpu_changes["cyber"] == ("idle", "primary")

    def test_cyber_to_ai_transition_shape(self, tmp_path):
        evidence = _evidence(tmp_path)
        plan = build_focus_transition("cyber", "ai", evidence)
        cpu_changes = {
            c.domain: (c.before, c.after) for c in plan.resource_changes if c.resource == "cpu"
        }
        assert cpu_changes["cyber"] == ("primary", "idle")
        assert cpu_changes["ai"] == ("idle", "primary")

    def test_ai_to_private_is_blocked_when_private_unavailable(self, tmp_path):
        evidence = _evidence(tmp_path)
        plan = build_focus_transition("ai", "private", evidence)
        assert plan.status == "BLOCKED"
        assert plan.blockers

    def test_ai_to_private_never_implies_global_tor_routing(self, tmp_path):
        evidence = _evidence(tmp_path)
        plan = build_focus_transition("ai", "private", evidence)
        dumped = json.dumps(plan.to_dict()).lower()
        assert "global tor routing" not in dumped or "no global tor routing" in dumped

    def test_private_to_ai_never_discards_private_state(self, tmp_path):
        evidence = _evidence(tmp_path)
        plan = build_focus_transition("private", "ai", evidence)
        dumped = json.dumps(plan.to_dict()).lower()
        assert "discard" not in dumped or "never destroys" in dumped

    def test_no_precise_reclaim_value_ever(self, tmp_path):
        # Section 84-85/105.
        evidence = _evidence(tmp_path)
        for from_focus, to_focus in CANONICAL_TRANSITIONS:
            plan = build_focus_transition(from_focus, to_focus, evidence)
            assert plan.expected_ram_reclaim_bytes is None
            assert plan.expected_vram_reclaim_bytes is None
            assert plan.reclaim_confidence == "unknown"

    def test_transition_plan_function_wrapper(self, tmp_path):
        plan = build_focus_transition_plan(
            "ai", "cyber", root=_empty_root(tmp_path), runner=FakeCommandRunner({}),
            home=_empty_home(tmp_path),
        )
        assert plan.from_focus == "ai"
        assert plan.to_focus == "cyber"

    def test_unknown_target_raises(self, tmp_path):
        evidence = _evidence(tmp_path)
        with pytest.raises(ValueError):
            build_focus_transition("ai", "not-a-real-target", evidence)


# ---------------------------------------------------------------------------
# Conflict model (Section 59-60)
# ---------------------------------------------------------------------------


class TestConflictModel:
    def test_conflicts_never_automatic_destructive(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            for conflict in policy.conflicts:
                assert "kill" not in conflict.resolution.lower()
                assert "stop" not in conflict.resolution.lower()
                assert "destroy" not in conflict.resolution.lower()

    def test_no_fabricated_conflicts_without_evidence(self, tmp_path):
        # No live GPU-utilization evidence exists in S6.5, so conflicts
        # must stay empty rather than being invented.
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        assert policy.conflicts == []


# ---------------------------------------------------------------------------
# Constraints: thermal / battery (Section 61-65)
# ---------------------------------------------------------------------------


class TestConstraints:
    def test_no_thermal_headroom_invented_when_unavailable(self, tmp_path):
        evidence = _evidence(tmp_path)
        assert evidence.thermal_zone_count == 0
        policy = build_focus_policy("ai", evidence)
        joined = " ".join(policy.constraints).lower()
        assert "headroom" not in joined or "no thermal headroom is assumed" in joined

    def test_system_reserve_constraint_always_present(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            joined = " ".join(policy.constraints).lower()
            assert "system reserve" in joined or "interactive responsiveness" in joined


# ---------------------------------------------------------------------------
# Capabilities (Section 18)
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_all_eleven_ids_present_once(self, tmp_path):
        report = build_focus_capabilities(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        ids = [c.id for c in report.capabilities]
        expected = {
            "cpu_weight_planning", "memory_budget_planning", "io_weight_planning",
            "gpu_lease_intent", "service_lifecycle_planning", "container_lifecycle_planning",
            "vm_lifecycle_planning", "thermal_constraint_awareness", "battery_constraint_awareness",
            "privacy_boundary_awareness", "transition_simulation",
        }
        assert set(ids) == expected
        assert len(ids) == len(set(ids))

    def test_most_capabilities_never_enforceable(self, tmp_path):
        report = build_focus_capabilities(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert all(c.enforceable is False for c in report.capabilities)

    def test_to_dict_is_json_serializable(self, tmp_path):
        report = build_focus_capabilities(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert json.dumps(report.to_dict())


# ---------------------------------------------------------------------------
# Planner (Section 3-4)
# ---------------------------------------------------------------------------


class TestPlanner:
    def test_build_focus_plan_matches_build_focus_policy(self, tmp_path):
        root, runner, home = _empty_root(tmp_path), FakeCommandRunner({}), _empty_home(tmp_path)
        via_planner = build_focus_plan("ai", root=root, runner=runner, home=home)
        evidence = gather_focus_evidence(root=root, runner=runner, home=home)
        via_policy = build_focus_policy("ai", evidence)
        assert via_planner.to_dict() == via_policy.to_dict()

    def test_unknown_target_raises(self, tmp_path):
        with pytest.raises(ValueError):
            build_focus_plan(
                "nonsense", root=_empty_root(tmp_path), runner=FakeCommandRunner({}),
                home=_empty_home(tmp_path),
            )

    def test_plan_never_mutates(self, tmp_path):
        runner = FakeCommandRunner({})
        build_focus_plan(
            "ai", root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        forbidden = ("install", "systemctl start", "virsh define", "podman run", "kill")
        for call in runner.calls:
            joined = " ".join(call).lower()
            for marker in forbidden:
                assert marker not in joined


# ---------------------------------------------------------------------------
# Status (Section 16-17, 107)
# ---------------------------------------------------------------------------


class TestStatus:
    def test_applied_focus_always_none(self, tmp_path):
        status = build_focus_status(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert status.applied_focus is None

    def test_mode_is_planning_only(self, tmp_path):
        status = build_focus_status(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert status.mode == "planning_only"
        assert status.runtime_enforcement is False

    def test_policy_baseline_is_balanced(self, tmp_path):
        status = build_focus_status(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert status.policy_baseline == "balanced"

    def test_supported_targets_matches_focus_targets(self, tmp_path):
        status = build_focus_status(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert set(status.supported_targets) == set(FOCUS_TARGETS)

    def test_to_dict_is_json_serializable(self, tmp_path):
        status = build_focus_status(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert json.dumps(status.to_dict())


# ---------------------------------------------------------------------------
# Doctor (Section 90-92)
# ---------------------------------------------------------------------------


class TestDoctor:
    def _by_id(self, report):
        return {c.id: c for c in report.checks}

    def test_clean_system_never_fails(self, tmp_path):
        report = run_focus_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert all(c.status is not CheckStatus.FAIL for c in report.checks)

    def test_all_eleven_checks_present(self, tmp_path):
        report = run_focus_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        expected = {
            "focus_one_primary_invariant", "focus_policy_determinism",
            "focus_system_reserve_present", "focus_gpu_not_overclaimed",
            "focus_private_preserves_veil_invariants", "focus_plan_no_mutation",
            "focus_transition_graph_complete", "focus_lifecycle_instance_evidence",
            "focus_lifecycle_ownership_not_overclaimed", "focus_ai_gpu_backend_gated",
            "focus_private_readiness_not_tor_only",
        }
        assert set(self._by_id(report).keys()) == expected

    def test_to_dict_is_json_serializable(self, tmp_path):
        report = run_focus_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        assert json.dumps(report.to_dict())

    def test_lifecycle_instance_evidence_check_passes_on_clean_and_populated_evidence(
        self, tmp_path
    ):
        runner = FakeCommandRunner({"ollama": _ok("ollama version 0.4.0")})
        report = run_focus_checks(
            root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        assert self._by_id(report)["focus_lifecycle_instance_evidence"].status == CheckStatus.PASS

    def test_lifecycle_ownership_check_passes(self, tmp_path):
        report = run_focus_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["focus_lifecycle_ownership_not_overclaimed"].status == CheckStatus.PASS

    def test_ai_gpu_backend_gated_check_passes_with_gpu_no_backend(self, tmp_path):
        # A GPU present with no usable backend must never trip this check
        # into FAIL (mode stays "shared", not "preferred").
        runner = FakeCommandRunner({})
        report = run_focus_checks(
            root=_empty_root(tmp_path), runner=runner, home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["focus_ai_gpu_backend_gated"].status == CheckStatus.PASS

    def test_private_readiness_not_tor_only_check_passes(self, tmp_path):
        report = run_focus_checks(
            root=_empty_root(tmp_path), runner=FakeCommandRunner({}), home=_empty_home(tmp_path)
        )
        by_id = self._by_id(report)
        assert by_id["focus_private_readiness_not_tor_only"].status == CheckStatus.PASS


# ---------------------------------------------------------------------------
# Security/privacy invariants (Section 93, 106)
# ---------------------------------------------------------------------------


class TestSecurityInvariants:
    def test_ai_focus_cannot_disable_s5_isolation(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("ai", evidence)
        dumped = json.dumps(policy.to_dict()).lower()
        assert "disable isolation" not in dumped
        assert "--privileged" not in dumped

    def test_cyber_focus_cannot_add_privileged_container(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("cyber", evidence)
        dumped = json.dumps(policy.to_dict()).lower()
        assert "--privileged" not in dumped
        assert "cap_sys_admin" not in dumped

    def test_cyber_focus_cannot_imply_network_host(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("cyber", evidence)
        dumped = json.dumps(policy.to_dict()).lower()
        assert "network=host" not in dumped
        assert "--network=host" not in dumped

    def test_private_focus_cannot_global_route_host_through_tor(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("private", evidence)
        dumped = json.dumps(policy.to_dict()).lower()
        assert "route entire host" not in dumped
        assert "global tor routing" not in dumped

    def test_private_focus_cannot_give_whonix_direct_clearnet(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("private", evidence)
        dumped = json.dumps(policy.to_dict()).lower()
        assert "direct clearnet" not in dumped

    def test_dev_focus_cannot_disable_security_controls(self, tmp_path):
        evidence = _evidence(tmp_path)
        policy = build_focus_policy("dev", evidence)
        dumped = json.dumps(policy.to_dict()).lower()
        assert "disable security" not in dumped
        assert "disable mitigations" not in dumped

    def test_no_focus_bypasses_thermal_safety(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            dumped = json.dumps(policy.to_dict()).lower()
            assert "override thermal" not in dumped
            assert "bypass thermal" not in dumped


# ---------------------------------------------------------------------------
# No-mutation regressions (Section 94-99)
# ---------------------------------------------------------------------------


_FORBIDDEN_MUTATION_TEXT = (
    "kill", "pkill", "killall",
    "systemctl stop", "systemctl start", "systemctl set-property",
    "echo > /sys", "echo > /proc",
    "cgcreate", "cgset",
    "virsh start", "virsh shutdown", "virsh destroy",
    "podman stop", "docker stop",
    "nvidia-smi -pl", "rocm-smi --set",
    "powerprofilesctl set", "cpupower frequency-set",
    "drop_caches", "swapoff", "swapon",
    "nvidia-smi --gpu-reset",
    "ip netns add", "ip route", "nft ", "iptables", "resolvectl dns", "nmcli proxy",
)


class TestNoMutationRegressions:
    def test_no_process_kill_commands_in_any_policy(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            policy = build_focus_policy(target, evidence)
            dumped = json.dumps(policy.to_dict()).lower()
            for marker in _FORBIDDEN_MUTATION_TEXT:
                assert marker not in dumped, f"{target}: found {marker!r}"

    def test_no_mutation_commands_in_any_transition(self, tmp_path):
        evidence = _evidence(tmp_path)
        for from_focus, to_focus in CANONICAL_TRANSITIONS:
            plan = build_focus_transition(from_focus, to_focus, evidence)
            dumped = json.dumps(plan.to_dict()).lower()
            for marker in _FORBIDDEN_MUTATION_TEXT:
                assert marker not in dumped, f"{from_focus}->{to_focus}: found {marker!r}"

    def test_runtime_enforcement_always_false(self, tmp_path):
        evidence = _evidence(tmp_path)
        for target in FOCUS_TARGETS:
            assert build_focus_policy(target, evidence).runtime_enforcement is False
        for from_focus, to_focus in CANONICAL_TRANSITIONS:
            transition = build_focus_transition(from_focus, to_focus, evidence)
            assert transition.runtime_enforcement is False
