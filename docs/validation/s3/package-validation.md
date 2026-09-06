# S3 — Package Validation

Environment: disposable `Ubuntu-26.04` WSL2 instance (see `README.md`).

## Initial sweep

A ~40-package script (`s3_check_packages.sh`, run and discarded inside
the disposable VM) ran `apt-cache policy <pkg>` followed by
`apt-get install --simulate -y <pkg>` for every candidate tool. One
real miss was found:

```
$ apt-cache policy p7zip-full
N: Unable to locate package p7zip-full
```

## Correction 1: `p7zip-full` → `7zip`

```
$ apt-cache search p7zip
7zip - 7-Zip file archiver with a high compression ratio
7zip-standalone - 7-Zip file archiver with a high compression ratio
$ apt-cache policy 7zip
7zip:
  Installed: (none)
  Candidate: 24.09+dfsg-1
```

Ubuntu 26.04 no longer ships `p7zip-full`; the archive-provided 7-Zip
port renamed to a plain `7zip` package. `packages.py`'s `BASE_TOOLS`
uses `7zip`, not `p7zip-full`.

## Correction 2 (naming quirk, not a missing package): `fd-find` / `bat`

Both packages exist and install cleanly, but under binary names that
do not match the upstream project name — a long-standing Debian
archive naming collision (another package already owned `fd`/`bat`
when these were packaged):

```
$ dpkg -L fd-find | grep bin
/usr/bin/fdfind
/usr/lib/cargo/bin/fd   (present but not on PATH by default)

$ dpkg -L bat | grep bin
/usr/bin/batcat
```

`packages.py` documents both in each `ToolDefinition.description`;
Serein's manifest requests the correct apt package name (`fd-find`,
`bat`) and does not claim a `fd`/`bat` binary will exist on `PATH`
without the user aliasing it themselves.

## Investigated and excluded: `yq`

```
$ apt-cache show yq
Package: yq
...
Depends: jq, python3-yaml, python3:any
Description: Front-end to jq that supports yaml, xml and toml
```

Ubuntu's `yq` is the Python (kislyuk) wrapper around `jq`, not the
popular Go `mikefarah/yq`. Since the two tools have incompatible
syntax and Serein cannot silently install "a yq" without knowing which
one a project's tooling expects, `yq` is excluded from the default
manifest entirely (documented in `docs/development/package-strategy.md`).

## Other binary-name/path spot checks (no surprises)

```
ripgrep      -> /usr/bin/rg
eza          -> /usr/bin/eza  (+ 'exa' compatibility symlink)
lldb         -> /usr/bin/lldb
clang        -> /usr/bin/clang, /usr/bin/clang++
gh           -> /usr/bin/gh          (2.46.0-4 — see git-strategy.md for the
                                       version-freshness trade-off)
podman       -> /usr/bin/podman      (5.7.0)
distrobox    -> /usr/bin/distrobox   (1.8.2.4)
ninja-build  -> /usr/bin/ninja
git-lfs      -> /usr/bin/git-lfs
gdb          -> /usr/bin/gdb
golang-go    -> /usr/bin/go          (go version go1.26.0 linux/amd64)
```

## Final corrected full-set simulation

```
$ PKGS='git git-lfs gh build-essential gcc g++ clang cmake ninja-build \
        pkg-config make gdb lldb strace ripgrep fd-find fzf jq bat eza \
        btop tree unzip zip 7zip rsync curl wget openssh-client gnupg \
        zoxide golang-go podman distrobox'
$ apt-get install --simulate -y $PKGS
...
0 upgraded, 0 newly installed, 0 to remove and 150 not upgraded.
$ echo $?
0
```

(0 newly-installed because most packages were already installed
individually during the exploration steps above, in the same
disposable VM — this confirms a clean, satisfiable dependency closure
with no conflicts and no unexpected removals, which is what the
simulation is checking for.)

## Verdict

```
S3_PACKAGE_EXISTENCE_VALIDATED=true
S3_DEPENDENCY_CLOSURE_VALIDATED=true   (0 conflicts, 0 unexpected removals)
S3_BINARY_NAME_QUIRKS_VALIDATED=true   (7zip, fdfind, batcat)
S3_NON_APT_TOOL_INSTALLATION_VALIDATED=false   (deliberately not executed — see README.md)
```
