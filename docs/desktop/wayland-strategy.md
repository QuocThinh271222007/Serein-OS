# Wayland Strategy

## Policy

```
preferred = Wayland
fallback  = X11, only when explicitly installed and required
```

## Why Wayland-first is not ideology here

This is not a stylistic preference — it follows Kubuntu 26.04 LTS's own
default. Per the verified release notes (`architecture.md`), Kubuntu
26.04 ships the Plasma Wayland session as the default **and only
supported** session; the X11 session package (`plasma-session-x11`) is
available in the archive but not installed by default and not supported
by the Kubuntu team. Serein's package manifest (`package-strategy.md`)
follows that same default: X11 session support is not part of the
baseline desktop package set.

**Validated in S1R:** installing the full 17-package Serein desktop set
(both simulated and for real, in a disposable Ubuntu 26.04 VM — see
`docs/validation/s1r/package-validation.md`) does not pull in
`plasma-session-x11` as a transitive dependency of anything. The policy
holds in practice, not just in the package list as authored.

## Fallback policy

A user or a later phase may still install `plasma-session-x11` — Serein
does not remove or block it, consistent with
[ADR-0002](../adr/0002-upstream-first.md) ("no ideological removal of
upstream-supplied capability"). What Serein does not do is:

- Install it by default (matches upstream Kubuntu's own choice).
- Pretend it is present when it isn't (`serein desktop doctor` reports
  X11 session detection honestly based on what's actually running).
- Design any Serein-specific feature that requires X11.

## Detection, not enforcement

`serein desktop status`/`doctor` report whichever session type is
*actually running* (`XDG_SESSION_TYPE`) — Wayland or X11 — without
treating an X11 session as an error. Running X11 produces `WARN`, not
`FAIL`, in `desktop doctor`: it is a supported-but-not-preferred state,
not a broken one.

## Development-host behavior

Doctor must never hard-fail merely because the *machine running Serein's
own CLI* (e.g. this Windows/CI development host) is not currently under a
Wayland session. When no `XDG_SESSION_TYPE` is set at all (headless, SSH,
CI, non-Linux), the Wayland-session check reports `SKIP`, not `FAIL`.

## What's explicitly deferred

NVIDIA/proprietary-driver Wayland compatibility is a hardware concern,
not a desktop-layer concern — it belongs to S2 (Hardware). S1 makes no
GPU-vendor-specific Wayland accommodations.
