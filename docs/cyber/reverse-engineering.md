# Reverse Engineering: Host Baseline vs. Toolbox

## Host baseline (light, always-on)

`file`, `binutils` (`readelf`/`objdump`/`strings`), `gdb`, `strace` —
`gdb` and `strace` are read directly from S3's `detect_cpp_status()`
output (`reverse.py`'s `detect_reverse_status()` calls it and reuses
the two fields) rather than re-probed independently, so there is
exactly one place in the codebase that owns "is gdb/strace installed."
`binutils` presence is confirmed either via an `objdump --version`
probe or, if that fails, a direct `dpkg -s binutils` check — either
signal is sufficient evidence of the package.

## Toolbox-tier (heavier, optional)

`radare2` and `ghidra` are `recommended_tier = "toolbox"`. `radare2` is
a real, current Ubuntu 26.04 package (`radare2`, `6.0.7+ds-1`, live-
confirmed). `ghidra` is **not** an Ubuntu package (confirmed absent
from the archive during live validation) — its classification is
`source_type = "official-upstream-binary"`, sourced from
`NationalSecurityAgency/ghidra`'s own GitHub Releases (current version
**12.1.3** as of this validation pass, distributed as a checksummed
archive, independently confirmed against the release page live during
this session — not a third-party repack, not a random mirror). S5 does
not download or install Ghidra; a future toolbox/user-managed
provisioning step would need to verify the release's published SHA-256
checksum before extracting it.

Cutter, Binary Ninja, and IDA are documented as optional/toolbox/
user-managed only — no proprietary software is downloaded or installed
by S5 in any case.

## Privacy: presence-only, never a filesystem scan

Detection is tool-presence-only. S5 never scans executables across the
filesystem, never indexes binaries, and never inspects a specific
file's contents to "detect RE capability" — `reverse.py`'s probes only
ever run a version-flag invocation of the tool binary itself
(`tests/test_cyber.py::TestReverse::test_never_scans_filesystem_binaries`
asserts no probe argument contains a path separator or glob character).
