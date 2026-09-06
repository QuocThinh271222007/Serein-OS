# S2R — CPU and Power-Profiles-Daemon Validation

Environment: disposable `Ubuntu-26.04` WSL2 instance (see `README.md`).

## `cpufreq` sysfs — confirmed absent under WSL2

```
$ ls -la /sys/devices/system/cpu/cpu0/cpufreq/
ls: cannot access '/sys/devices/system/cpu/cpu0/cpufreq/': No such file or directory
```

WSL2 exposes no `cpufreq` interface at all. This is not evidence either
way about real `amd-pstate-epp`/`intel_pstate`/`acpi-cpufreq` sysfs shape
on bare metal — it only confirms that `cpu_policy.py`'s
`cpufreq_present = False` graceful-degradation path is exercised
correctly here (`serein hardware plan` produces `SKIP` for `cpu.epp`,
not a crash or a false claim of governor control).

```
S2R_CPU_SYSFS_LIVE=BLOCKED
```

## `power-profiles-daemon` — package and marker paths confirmed

```
$ apt-cache policy power-profiles-daemon
power-profiles-daemon:
  Installed: (none)
  Candidate: 0.30-2
  Version table:
     0.30-2 500
        500 http://archive.ubuntu.com/ubuntu resolute/main amd64 Packages
```

Installed for real; exact shipped marker paths confirmed via `dpkg -L`:

```
/usr/bin/powerprofilesctl
/usr/lib/systemd/system/power-profiles-daemon.service
/usr/share/dbus-1/system-services/net.hadess.PowerProfiles.service
/usr/share/dbus-1/system-services/org.freedesktop.UPower.PowerProfiles.service
```

These are **exactly** the two markers `power_policy.py`'s `_PPD_MARKERS`
already checked (`usr/bin/powerprofilesctl` and `usr/lib/systemd/system/
power-profiles-daemon.service`). No code change was needed for PPD
detection — Section 31 of the S2R brief's "provisionally accepted"
status is confirmed correct.

```
S2R_PPD_POLICY_REVALIDATED=true
```
