# Desktop Installation Plan

## Mapping onto the S0 installer contract

The S0 installer contract (`docs/architecture/installer-contract.md`)
defines: `Discover → Resolve → Plan → Validate → Apply → Verify → Record`.
S1 does not introduce a parallel architecture — it fills in the
*read-only* half of that lifecycle for the desktop domain and leaves the
mutating half (`Apply`/`Verify`/`Record` execution) to a future installer
engine phase, exactly as the S0 contract anticipates ("no mutation is
implemented in S0[/S1]; this principle governs the contract that future
phases must satisfy").

| Lifecycle step | S1 status | Where |
|---|---|---|
| **Discover** | Implemented (read-only) | `desktop.detect` — installed components, live session, config-marker state. |
| **Resolve** | Implemented (static) | `desktop.packages`/`desktop.config` — the desktop profile's package/config requirements are fixed declarative data in S1; nothing yet resolves against *other* installed profiles or conflicts. |
| **Plan** | Implemented | `desktop.plan.build_desktop_plan()` — deterministic, pure function of `packages.py`/`config.py`; no host I/O, callable identically twice. |
| **Validate** | Not implemented | Would check the plan against constraints (disk space, profile conflicts) before Apply exists to need it. |
| **Apply** | Not implemented — by design | No code path in this repository writes `/etc/xdg/*`, installs packages, or touches SDDM config. |
| **Verify** | Partially implemented | `desktop.doctor` provides the individual checks (`desktop_plasma_availability`, etc.) a future Apply step would re-run post-install; it just has nothing to verify yet since nothing applies. |
| **Record** | Not implemented | The `/etc/serein/desktop/config-version` marker is *read* by `desktop.detect`/`desktop.doctor` today; nothing writes it until Apply exists. |

## `serein desktop plan` output shape

```
Desktop installation plan

Packages:
  install plasma-desktop
  install plasma-workspace
  ... (all packages from desktop.packages.all_packages(), sorted)

System configuration:
  install_packages        Install N desktop packages (see 'packages').
  install_xdg_defaults     Install /etc/xdg/{kdeglobals,kwinrc} ...
  install_lookandfeel      Install org.serein.desktop Look-and-Feel ...
  install_sddm_dropin      Install /etc/sddm.conf.d/90-serein.conf ...
  install_konsole_profile  Install the Serein Konsole profile ...
  record_config_version    Write /etc/serein/desktop/config-version = 1.

User configuration:
  first_login_lookandfeel   New sessions default to Serein's layout ...
  first_login_konsole_default  New sessions may select the Serein profile ...

Verification:
  desktop_plasma_availability
  desktop_kwin_availability
  desktop_sddm_availability
  desktop_wayland_session
  desktop_config_contract
  desktop_required_resources
```

`serein desktop plan --json` emits the same content as
`schemas/desktop-plan.schema.json`-validated JSON.

## Why the plan is deterministic

`build_desktop_plan()` takes no arguments and performs no filesystem or
environment reads — it is a pure transform of two Python modules
(`packages.py`, `config.py`). Calling it twice, on any machine, in any
order, produces byte-identical output. This is deliberate: a plan
described in the docs above is worthless if the tool doesn't reproduce it
exactly, and it means `serein desktop plan --json` is safe to diff across
runs/CI without special normalization.
