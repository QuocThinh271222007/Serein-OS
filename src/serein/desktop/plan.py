"""Deterministic desktop installation plan.

Maps onto the S0 installer contract's Discover -> Resolve -> Plan stages
(``docs/desktop/installation-plan.md``); Validate/Apply/Verify/Record are
not implemented here. ``build_desktop_plan`` takes no arguments and
performs no I/O — it is a pure function of ``packages.py``/``config.py``,
so it is safe to call from any environment (including this development
host) and always produces byte-identical output.
"""

from __future__ import annotations

from serein.desktop.models import DESKTOP_CONFIG_VERSION, SCHEMA_VERSION, DesktopPlan, PlanStep
from serein.desktop.packages import all_packages


def build_desktop_plan() -> DesktopPlan:
    packages = all_packages()

    system_configuration = [
        PlanStep(
            "system",
            "install_packages",
            f"Install {len(packages)} desktop packages (see 'packages').",
        ),
        PlanStep(
            "system",
            "install_xdg_defaults",
            "Install /etc/xdg/kdeglobals and /etc/xdg/kwinrc as the Serein "
            "distribution-defaults layer (never overwrites ~/.config).",
        ),
        PlanStep(
            "system",
            "install_lookandfeel",
            "Install the org.serein.desktop Look-and-Feel package "
            "(panel layout, color scheme, icon theme reference).",
        ),
        PlanStep(
            "system",
            "install_sddm_dropin",
            "Install /etc/sddm.conf.d/90-serein.conf (Breeze theme; "
            "autologin left explicitly disabled).",
        ),
        PlanStep(
            "system",
            "install_konsole_profile",
            "Install the Serein Konsole profile and color scheme as "
            "available, not forced, choices.",
        ),
        PlanStep(
            "system",
            "record_config_version",
            f"Write /etc/serein/desktop/config-version = {DESKTOP_CONFIG_VERSION}.",
        ),
    ]

    user_configuration = [
        PlanStep(
            "user",
            "first_login_lookandfeel",
            "New user sessions default to the Serein Look-and-Feel unless "
            "the user already has a layout of their own.",
        ),
        PlanStep(
            "user",
            "first_login_konsole_default",
            "New user sessions may select the Serein Konsole profile; "
            "existing user profiles are left untouched.",
        ),
    ]

    verification = [
        "desktop_plasma_availability",
        "desktop_kwin_availability",
        "desktop_sddm_availability",
        "desktop_wayland_session",
        "desktop_config_contract",
        "desktop_required_resources",
    ]

    return DesktopPlan(
        schema_version=SCHEMA_VERSION,
        packages=packages,
        system_configuration=system_configuration,
        user_configuration=user_configuration,
        verification=verification,
    )
