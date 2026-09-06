# S1R — What Remains BLOCKED After This Pass

None of the following are evidence of a defect — each is a gap in what
this specific environment (a disposable WSL2 VM, no physical or virtual
GPU display, no VT/DRM device) can exercise. Per Section 38 of the S1R
brief, these do not block S1 merge on their own.

## SDDM interactive login (credential prompt, wrong-password rejection)

SDDM needs to own a real VT/DRM device to display its login screen; WSL2
exposes neither. The drop-in mechanism, its precedence, its exact
key/section format, and its static content (no autologin, no PAM changes)
were all verified against the real shipped `sddm` and
`kubuntu-settings-desktop` packages instead (`sddm-validation.md`) — this
is the one piece that evidence style cannot reach, not evidence that
anything is wrong.

## HiDPI scaling behavior

`S1R_HIDPI_VALIDATION=BLOCKED`. KWin's `--virtual` backend produces a
headless framebuffer with no compositing pipeline exercised the way a
real display's scale factor would be — testing 100%/150%/200% scaling
meaningfully requires an actual rendered output, which was not available.

## Multi-monitor behavior

`S1R_MULTIMONITOR_VALIDATION=BLOCKED`, for the same reason as HiDPI —
`--virtual` mode was run single-output only. No hardcoded resolution or
output-count assumption exists anywhere in `desktop/kwin/kwinrc` or the
Look-and-Feel layout script to begin with (the layout script only
positions one bottom panel and does not reference screen geometry), so
the risk this validation would catch is low, but it was not exercised.

## Full nested Wayland session inside WSLg's own compositor

The first attempt (`kwin_wayland` nested inside WSLg's bundled Weston-like
compositor) failed: `wp_single_pixel_buffer_manager_v1 isn't supported by
the host compositor`. This is a WSLg limitation (its compositor doesn't
implement a Wayland protocol extension KWin 6.6's nested backend
requires), not a Serein configuration defect — worked around by using
KWin's own `--virtual` headless backend instead (the same one upstream
KWin uses for its automated test suite), which produced the real,
decisive panel-layout/first-login evidence in
`plasma-runtime-validation.md`.

## Physical GPU / real display rendering

Not available in this environment at all (WSL2, no dedicated GPU
passthrough for display purposes). Deferred to a genuine hardware or
type-2-hypervisor (VirtualBox/QEMU-with-display) validation pass if one
becomes available in a future phase.

## Package dependency closure beyond `apt-get --simulate`

`apt-get install --simulate` and then a real, full, non-simulated install
both succeeded cleanly (0 removals, 0 conflicts) — this is real dependency
closure evidence, not merely simulated. What was *not* tested: behavior
of `apt-get install` under partial-failure conditions (e.g. a mirror
outage mid-transaction) or on an architecture other than `x86_64`.

## Summary

```
S1R_HIDPI_VALIDATION=BLOCKED
S1R_MULTIMONITOR_VALIDATION=BLOCKED
S1R_SDDM_AUTHENTICATION_PASS=PARTIAL (static content verified; interactive flow BLOCKED)
```

None of Section 37's high-severity blockers were found. The one real
defect this pass did find (`breeze-gtk` → `breeze-gtk-theme`) was fixed
and is recorded in `package-validation.md`.
