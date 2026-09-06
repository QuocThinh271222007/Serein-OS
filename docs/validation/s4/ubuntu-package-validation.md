# S4 — Ubuntu Package Validation

Environment: disposable `Ubuntu-26.04` WSL2 instance (see `README.md`).

## Headline finding: CUDA Toolkit and ROCm are now Ubuntu-repository packages

The S4 brief's initial architecture assumed (consistent with older
Ubuntu LTS releases and general community knowledge) that a CUDA
Toolkit requires NVIDIA's own apt repository and ROCm requires AMD's
own `amdgpu-install` mechanism. Live evidence contradicts this for
Ubuntu 26.04:

```
$ apt-cache policy cuda-toolkit
cuda-toolkit:
  Candidate: 13.1.1-0ubuntu1
     500 http://archive.ubuntu.com/ubuntu resolute/multiverse amd64 Packages

$ apt-cache policy rocm rocminfo rocm-smi
rocm:
  Candidate: 7.1.0-0ubuntu6
     500 http://archive.ubuntu.com/ubuntu resolute/universe amd64 Packages
rocminfo:
  Candidate: 7.1.1-0ubuntu1
     500 http://archive.ubuntu.com/ubuntu resolute/universe amd64 Packages
rocm-smi:
  Candidate: 7.1.1-0ubuntu1
     500 http://archive.ubuntu.com/ubuntu resolute/universe amd64 Packages
```

The `-0ubuntuN` revision suffix and the `archive.ubuntu.com` origin
(with no third-party source configured — verified, see `README.md`)
confirm these are genuine Ubuntu-archive-native builds, not a
pre-added PPA. This is a real, current-generation packaging change:
Ubuntu 26.04 ships CUDA 13.1 and ROCm 7.1 directly. **Corrected in
`packages.py`**: both `cuda-toolkit` and `rocm` are now classified
`source_type="ubuntu-repository"` with real `package` names, not
`"official-upstream-repository"` — exactly the kind of stale
assumption the S4 brief's Section 4 required verifying against current
reality rather than encoding from memory.

`nvidia-container-toolkit` was checked for the same possibility and
found genuinely absent from Ubuntu's own archive:

```
$ apt-cache policy nvidia-container-toolkit
$ echo $?
0
(no output - package not found)

$ sudo apt-get install --simulate -y nvidia-container-toolkit
E: Unable to locate package nvidia-container-toolkit
```

This one remains correctly classified `"official-upstream-repository"`
(NVIDIA's own apt repository is genuinely required).

## NVIDIA driver branches (confirms a current, non-stale range)

```
$ apt list --all-versions 2>/dev/null | grep -E '^nvidia-driver-[0-9]+/'
nvidia-driver-570 -> 580.173.02-0ubuntu0.26.04.1
nvidia-driver-575 -> 575.64.03-0ubuntu4
nvidia-driver-580 -> 580.173.02-0ubuntu0.26.04.1
nvidia-driver-590 -> 595.84-0ubuntu0.26.04.1
nvidia-driver-595 -> 595.84-0ubuntu0.26.04.1
nvidia-driver-610 -> 610.43.02-0ubuntu0.26.04.1
```

`ubuntu-drivers-common` (`1:0.10.9`, `resolute/main`) is real and
present, confirming the `ubuntu-drivers autoinstall` mechanism
`docs/ai/nvidia-strategy.md` recommends is genuinely available.

## ffmpeg

```
$ apt-cache policy ffmpeg
ffmpeg:
  Candidate: 7:8.0.1-3ubuntu2
     500 http://archive.ubuntu.com/ubuntu resolute/universe amd64 Packages
```

A normal, current Ubuntu archive package — no naming surprise (unlike
S3's `p7zip-full`/`fd-find` findings).

## Combined dependency-closure simulation

```
$ sudo apt-get install --simulate -y ffmpeg cuda-toolkit rocm ubuntu-drivers-common
...
7 upgraded, 396 newly installed, 0 to remove and 147 not upgraded.
$ echo $?
0
```

Clean, satisfiable closure — 0 removals, 0 errors. The large
newly-installed count is expected: CUDA Toolkit and ROCm both pull in
substantial dependency trees (compilers, math/BLAS/FFT libraries,
debugger support) by design.

## Verdict

```
S4_UBUNTU_PACKAGE_VALIDATION=true
S4_CUDA_TOOLKIT_SOURCE_CORRECTED=true   (ubuntu-repository, not official-upstream-repository)
S4_ROCM_SOURCE_CORRECTED=true           (ubuntu-repository, not official-upstream-repository)
S4_NVIDIA_CONTAINER_TOOLKIT_CONFIRMED_THIRD_PARTY=true
S4_DEPENDENCY_CLOSURE_VALIDATED=true    (0 conflicts, 0 unexpected removals)
S4_NON_APT_TOOL_INSTALLATION_VALIDATED=false   (deliberately not executed — see README.md)
```
