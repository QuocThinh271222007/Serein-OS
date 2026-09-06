# S1R Validation A/B — Package Availability and Dependency Closure

Environment: disposable `Ubuntu-26.04` WSL2 instance (see `README.md`).
`apt-get update` confirmed live against `archive.ubuntu.com`/
`security.ubuntu.com` (`resolute`, `resolute-updates`,
`resolute-security`, `resolute-backports` — all `Hit`, no `Ign`/`Err`).

## Per-package existence (`apt-cache policy`)

All 17 packages from `src/serein/desktop/packages.py` were queried
individually. **16 of 17 existed as authored; one did not.**

| Package | Candidate version | Result |
|---|---|---|
| plasma-desktop | 4:6.6.6-0ubuntu0.1 | OK |
| plasma-workspace | 4:6.6.6-0ubuntu0.1 | OK |
| kwin-wayland | 4:6.6.6-0ubuntu0.1 | OK |
| systemsettings | 4:6.6.5-0ubuntu0.1 | OK |
| sddm | 0.21.0+git20250502.4fe234b-2ubuntu3 | OK |
| sddm-theme-breeze | 4:6.6.6-0ubuntu0.1 | OK |
| dolphin | 4:25.12.3-0ubuntu1 | OK |
| konsole | 4:25.12.3-0ubuntu1 | OK |
| ark | 4:25.12.3-0ubuntu1 | OK |
| xdg-desktop-portal-kde | 6.6.6-0ubuntu0.1 | OK |
| plasma-nm | 4:6.6.6-0ubuntu0.1 | OK |
| plasma-pa | 4:6.6.5-0ubuntu0.1 | OK |
| print-manager | 6:6.6.5-0ubuntu0.1 | OK |
| kinfocenter | 4:6.6.6-0ubuntu0.1 | OK |
| breeze | 4:6.6.5-0ubuntu0.1 | OK |
| ~~breeze-gtk~~ | — | **MISSING — does not exist in the archive** |
| plasma-integration | 6.6.5-0ubuntu0.1 | OK |

Confirms the Plasma 6.6 / KDE Gear 25.12.3 baseline documented in
`docs/desktop/architecture.md`.

### Defect found and fixed: `breeze-gtk` → `breeze-gtk-theme`

`apt-cache policy breeze-gtk` returned `Candidate: (none)`. `apt-cache
search breeze` on the real archive shows the actual package is
**`breeze-gtk-theme`** ("GTK theme built to match KDE's Breeze"),
confirmed installable (`Candidate: 6.6.4-0ubuntu1`). This was a real
package-name error in the original S1 manifest, not a hypothetical risk.

**Fixed in this pass:**
- `src/serein/desktop/packages.py` — `appearance` group
- `profiles/desktop/desktop.profile.json` — `packages` array
- `docs/desktop/package-strategy.md`, `docs/adr/0005-kde-plasma-desktop.md`

No test hardcoded the old name (`tests/test_desktop.py` derives its
expectations from `all_packages()`), so no test needed correction beyond
the new regression coverage this pass adds.

## Dependency closure (`apt-get install --simulate`, full set together)

With the corrected package name, simulating the full 17-package set
together:

```
The following packages will be upgraded:
  ... (4 packages)
4 upgraded, 984 newly installed, 0 to remove and 150 not upgraded.
```

- **0 to remove** — no conflict forced removal of anything.
- **No missing packages** — the simulate step completed with exit 0
  (initial run with the unfixed name failed with
  `E: Unable to locate package breeze-gtk`, exit 100; the corrected run
  succeeded).
- **984 newly installed** is expected and not a package-set defect: the
  baseline WSL2 Ubuntu image is a minimal server rootfs with no X11/Wayland
  client libraries, fontconfig data, or audio stack at all, unlike a real
  Kubuntu ISO's base image which already includes most of that. This
  number reflects the gap between "minimal server" and "graphical
  workstation," not scope creep in Serein's own package list.
- Checked the resulting package list by name for any kitchen-sink
  application (`libreoffice`, `akonadi`, `kontact`, `amarok`, `k3b`,
  `thunderbird`, `firefox`, `chromium`) — **none appear**, confirming the
  package-set quality goal (Section 7 of the S1R brief): the curated list
  does not implicitly drag in full applications beyond the declared
  desktop-shell scope.

## Real (non-simulated) install

The full corrected set was then actually installed (`apt-get install -y
...`, no `--simulate`) inside the disposable instance — safe here because
the instance is isolated and disposable, never the developer's host. This
produced a real installed Plasma 6.6 system used for the KPackage/
config-parsing/color-scheme validation in `plasma-runtime-validation.md`.
Exit code and any warnings from that install are recorded there.

## Verdict

```
S1R_PACKAGE_AVAILABILITY_PASS=true   (after the breeze-gtk-theme fix)
S1R_PACKAGE_DEPENDENCY_CLOSURE_PASS=true
S1R_PACKAGE_CONFLICT_COUNT=0
```
