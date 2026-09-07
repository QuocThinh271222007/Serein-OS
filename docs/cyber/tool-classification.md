# Tool Classification Model

## One canonical tier per tool, never a second drifting list

Every `CyberToolDefinition` in `src/serein/cyber/tools.py` carries
exactly one `recommended_tier` (`"host"|"toolbox"|"vm"|"user-managed"`).
`planner.py` and `capabilities.py` both filter/consume this single
field — neither module maintains its own separate tier list. This is
enforced by `tests/test_cyber.py::TestTools::test_host_tools_helper_matches_tier_filter`
and `test_toolbox_tools_helper_matches_tier_filter`, and by the doctor's
`cyber_package_manifest` check (`FAIL`s if any tool's tier isn't one of
the four recognized values).

## Fields

```python
id: str                      # stable identifier, matches the real apt
                              # package name where one exists
name: str
category: str                # one of CYBER_CATEGORIES
source_type: str              # where the artifact actually comes from
package: str | None           # apt package name, or None (non-apt tools)
recommended_tier: str          # host / toolbox / vm / user-managed
requires_root: bool            # install-time root requirement
requires_network_privilege: bool
reversible: bool
risk: str                     # none / low / medium / high
reason: str                   # why this tier, in prose
```

`source_type` and `recommended_tier` are deliberately distinct fields
with distinct valid-value sets — a real bug caught during this phase's
own development had `burpsuite`'s `source_type` mistakenly set to the
tier value `"user-managed"` (a valid tier, but not a valid
`source_type`), which the `cyber_package_manifest` doctor check
correctly `FAIL`ed on. Fixed to `source_type = "optional"` with the
tier staying `"user-managed"` in its own field — regression-tested
(`TestTools::test_burpsuite_is_user_managed_not_a_source_type`).

## Risk is about installation/host impact, not moral judgment

`risk` (`none`/`low`/`medium`/`high`) reflects install footprint and
host-safety impact, never a value judgment about the tool's purpose:
`dig` is `none`/`low`, `nmap` is `low` (detection only — no target is
ever scanned by Serein itself), a Wireshark capture-privilege *change*
would be `medium` (Serein never performs one), `hashcat`/Metasploit are
toolbox-tier regardless of risk label, and malware-analysis tooling is
`high`/VM-tier. Risk is never inferred from a tool's name alone
(Section 62) — each tool's `risk` is set individually based on what
installing/using *that specific tool* actually does.

## Live-validated source strategy

For every non-apt tool, `tools.py` records the real official source
rather than a convenient shortcut. The choice is never "Ubuntu apt by
inertia" or "upstream by inertia" — each tool's `tools.py` `reason`
field cites the actual version comparison behind the decision (S5R
Section 24-26):

| Tool | source_type | Real source / rationale |
|---|---|---|
| `ghidra` | `official-upstream-binary` | GitHub Releases, `NationalSecurityAgency/ghidra` (no Ubuntu package exists at all) |
| `metasploit-framework` | `official-upstream-repository` | Rapid7's own apt-like installer (no Ubuntu package exists at all) |
| `mitmproxy` | `python-package-index` (`uv`-managed) | Ubuntu 26.04 package (`8.1.1-4`) is significantly stale vs. upstream's current `12.2.3` (live-confirmed, 4-major-version gap) — apt is available but deliberately not used |
| `ffuf` | `ubuntu-repository` | Ubuntu 26.04's `2.1.0-1build1` is one minor release behind upstream's current `2.2.1` (live-confirmed) — close enough to prefer apt over a Go-binary install |
| `gobuster` | `ubuntu-repository` | Ubuntu 26.04's `3.8.2-1` exactly matches upstream's current `v3.8.2` tag (live-confirmed) — apt preferred |
| `sqlmap` | `ubuntu-repository` | Ubuntu 26.04's `1.10.4-1` (live-confirmed); upstream has no frequent tagged release beyond `1.10` and develops continuously on `master` — Ubuntu's packaged snapshot is preferred over an ad hoc git-clone install |
| `burpsuite` | `optional` | user-managed GUI download, no automated installer or license acceptance |

This table, `tools.py`'s per-tool `reason` field, and
`docs/validation/s5/package-validation.md`'s live version evidence are
kept in agreement — a tool is never described as "upstream-only" here
while validation shows a real, current Ubuntu package exists without a
documented reason for skipping it. No unofficial `curl | sh` scripts,
no random PPAs, and no third-party repacks are used when an official
source already exists — every `source_type` value is one of a small,
fixed, documented set (`_VALID_SOURCE_TYPES` in `doctor.py`), never
invented ad hoc per tool.
