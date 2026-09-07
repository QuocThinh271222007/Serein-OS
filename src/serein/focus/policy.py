"""The canonical focus policy computation (Section 49/88):
``build_focus_policy(target, evidence)`` is the single source of truth
every CLI surface (``capabilities.py``, ``planner.py``, ``status.py``,
``doctor.py``) consumes - none of them derives domain roles or
resource intent independently, avoiding the exact class of divergence
bug S5R/S6R had to fix after the fact in earlier phases.
"""

from __future__ import annotations

from serein.focus.evidence import FocusEvidence
from serein.focus.models import (
    FOCUS_DOMAINS,
    FOCUS_PLAN_SCHEMA_VERSION,
    FOCUS_TARGETS,
    DomainRole,
    FocusPolicy,
)
from serein.focus.resources import (
    build_conflicts,
    build_constraints,
    build_gpu_intent,
    build_lifecycle_intents,
    build_memory_intent,
    build_resource_intents,
)

#: Section 45-48's canonical secondary/idle/off role assignment for
#: each non-balanced target, applied to the three domains that are not
#: that target's own primary domain.
_ROLE_TABLE: dict[str, dict[str, str]] = {
    "dev": {"ai": "secondary", "cyber": "idle", "private": "off"},
    "ai": {"dev": "secondary", "cyber": "idle", "private": "off"},
    "cyber": {"dev": "secondary", "ai": "idle", "private": "off"},
    "private": {"dev": "secondary", "ai": "secondary", "cyber": "idle"},
}


# ---------------------------------------------------------------------------
# Domain readiness (Section 76-80) - reused by policy, status, and the
# `serein focus domains` CLI command alike.
# ---------------------------------------------------------------------------


def _dev_readiness(evidence: FocusEvidence) -> tuple[str, str]:
    installed = {
        c.id for c in evidence.development_capabilities.capabilities if c.installed
    }
    toolchains = {"python_uv", "node_runtime", "rustup", "go_toolchain", "cpp_toolchain"}
    found = installed & toolchains
    if found:
        return (
            "available",
            f"{len(found)} development toolchain(s) confirmed installed (S3 evidence).",
        )
    return (
        "limited",
        "No language toolchain confirmed installed yet - basic shell/Git "
        "tooling may still be usable (S3 evidence, Section 80).",
    )


def _ai_readiness(evidence: FocusEvidence) -> tuple[str, str]:
    by_id = {c.id: c for c in evidence.ai_capabilities.capabilities}
    gpu_backend_usable = any(
        by_id.get(cid) is not None and by_id[cid].usable is True
        for cid in ("pytorch_cuda", "pytorch_rocm")
    )
    if gpu_backend_usable:
        return "available", "A GPU-backed PyTorch build is confirmed usable (S4 evidence)."
    cpu_usable = by_id.get("pytorch_cpu") is not None and by_id["pytorch_cpu"].usable is True
    runtime_installed = any(
        by_id.get(cid) is not None and by_id[cid].installed
        for cid in ("ollama", "llama_cpp")
    )
    if cpu_usable or runtime_installed:
        return (
            "available",
            "CPU-only AI inference is usable, or a local AI runtime is "
            "installed (S4 evidence) - a discrete GPU is not required "
            "(Section 78).",
        )
    return (
        "limited",
        "No AI runtime or PyTorch build confirmed installed yet; CPU "
        "inference remains structurally possible (S4 evidence).",
    )


def _cyber_readiness(evidence: FocusEvidence) -> tuple[str, str]:
    by_id = {c.id: c for c in evidence.cyber_capabilities.capabilities}
    toolbox = by_id.get("container_toolbox")
    vm = by_id.get("vm_isolation")
    if (toolbox is not None and toolbox.installed) or (vm is not None and vm.usable):
        return (
            "available",
            "Isolated cyber toolbox and/or VM isolation is available (S5 evidence).",
        )
    return (
        "limited",
        "Host-tier cyber diagnostics remain usable even without a "
        "toolbox/VM (S5 evidence, Section 79).",
    )


def _private_readiness(evidence: FocusEvidence) -> tuple[str, str]:
    """S6.5R Corrective D (Section 25-31): Tor *client* usability alone
    must never upgrade private readiness to ``"available"`` - S6 itself
    keeps "Tor client usable" genuinely separate from "application
    routed via Tor" / "private workspace usable" / "Whonix usable"
    (`docs/veil/threat-model.md`), and Focus must not re-collapse that
    distinction. ``"available"`` requires one of the mechanisms that
    would actually constitute a *complete* private-browsing/isolation
    boundary - ``private_workspace``, ``whonix_vm``, or ``tor_browser``
    - to be confirmed ``usable`` (S6 evidence); a bare-usable Tor
    client, or any mechanism merely *installed*, is ``"limited"``."""
    by_id = {c.id: c for c in evidence.veil_capabilities.capabilities}
    tor = by_id.get("tor_client")
    browser = by_id.get("tor_browser")
    workspace = by_id.get("private_workspace")
    whonix = by_id.get("whonix_vm")

    complete_boundary_usable = any(
        capability is not None and capability.usable is True
        for capability in (workspace, whonix, browser)
    )
    if complete_boundary_usable:
        return (
            "available",
            "A complete private-workspace/Whonix/Tor-Browser boundary is "
            "confirmed usable (S6 evidence).",
        )

    tor_usable = tor is not None and tor.usable is True
    if tor_usable:
        return (
            "limited",
            "Tor client is usable, but no complete private-workspace/"
            "browser/Whonix boundary is confirmed usable (S6 evidence, "
            "Section 42) - Tor client usability alone does not mean a "
            "private focus is fully realizable (S6.5R Corrective D).",
        )

    something_present = any(
        capability is not None and capability.installed
        for capability in (tor, browser, workspace, whonix)
    )
    if something_present:
        return (
            "limited",
            "Some privacy mechanism is installed but not yet confirmed "
            "usable (S6 evidence).",
        )
    return (
        "blocked",
        "No usable Tor client, Tor Browser, private workspace, or Whonix "
        "readiness detected (S6 evidence, Section 42) - a private focus "
        "cannot be realized yet.",
    )


_READINESS_FUNCS = {
    "dev": _dev_readiness,
    "ai": _ai_readiness,
    "cyber": _cyber_readiness,
    "private": _private_readiness,
}


def evaluate_domain_readiness(evidence: FocusEvidence) -> dict[str, tuple[str, str]]:
    """Domain -> (readiness, reason) - the single evaluation every
    consumer (policy/status/`focus domains`) shares (Section 76)."""
    return {domain: _READINESS_FUNCS[domain](evidence) for domain in FOCUS_DOMAINS}


# ---------------------------------------------------------------------------
# Domain role assignment (Section 6-8, 44-48)
# ---------------------------------------------------------------------------


def evaluate_domain_roles(target: str, evidence: FocusEvidence) -> list[DomainRole]:
    """The one-primary invariant holds by construction here (Section
    7): at most one ``DomainRole`` is ever built with ``state ==
    "primary"`` - exactly one when ``target`` is a professional domain,
    zero when ``target == "balanced"``."""
    readiness = evaluate_domain_readiness(evidence)
    roles: list[DomainRole] = []
    for domain in FOCUS_DOMAINS:
        domain_readiness, reason = readiness[domain]
        if target == domain:
            state = "primary"
        elif target == "balanced":
            # Section 44: balanced never aggressively quiesces anything -
            # every domain is "secondary" (equal, non-primary footing)
            # unless it is not even readily available.
            state = "off" if domain_readiness == "blocked" else "secondary"
        else:
            state = _ROLE_TABLE[target][domain]
        roles.append(
            DomainRole(domain=domain, state=state, readiness=domain_readiness, reason=reason)
        )
    return roles


# ---------------------------------------------------------------------------
# Canonical policy function (Section 88)
# ---------------------------------------------------------------------------


def build_focus_policy(target: str, evidence: FocusEvidence) -> FocusPolicy:
    if target not in FOCUS_TARGETS:
        raise ValueError(f"unknown focus target: {target!r}")

    domain_roles = evaluate_domain_roles(target, evidence)
    resource_intents = build_resource_intents(domain_roles)
    memory_intent = build_memory_intent(domain_roles, evidence)
    gpu_intent = build_gpu_intent(domain_roles, evidence)
    lifecycle_intents = build_lifecycle_intents(domain_roles, evidence)
    conflicts = build_conflicts(gpu_intent)
    constraints = build_constraints(evidence)

    if target == "balanced":
        primary_domain = None
        readiness = "available"
        rationale = (
            "balanced means no professional domain owns primary-focus "
            "preference (Section 5) - interactive responsiveness and "
            "normal background fairness are the only policy targets; no "
            "GPU/VM/container preference and no privacy routing."
        )
    else:
        primary_domain = target
        role = next(r for r in domain_roles if r.domain == target)
        readiness = role.readiness
        rationale = f"{target} is the requested primary focus. {role.reason}"

    return FocusPolicy(
        schema_version=FOCUS_PLAN_SCHEMA_VERSION,
        target=target,
        primary_domain=primary_domain,
        readiness=readiness,
        domain_roles=domain_roles,
        resource_intents=resource_intents,
        memory_intent=memory_intent,
        gpu_intent=gpu_intent,
        lifecycle_intents=lifecycle_intents,
        conflicts=conflicts,
        constraints=constraints,
        rationale=rationale,
    )


__all__ = [
    "build_focus_policy",
    "evaluate_domain_readiness",
    "evaluate_domain_roles",
]
