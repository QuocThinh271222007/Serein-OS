# Git / GitHub Strategy

## Git and Git LFS

Both are plain Ubuntu 26.04 packages (`git`, `git-lfs`), installed as
part of the `git` package group. **Serein never writes `~/.gitconfig`**
— no `user.name`, `user.email`, signing key, or credential helper is
ever configured automatically. `git.py`'s detection is limited to
`git --version`; it never reads `~/.gitconfig` or any repository state.

A non-identity recommended-defaults template exists at
`development/git/recommended.gitconfig`
(`init.defaultBranch=main`, `pull.rebase=false`, `rerere.enabled=true`)
— **never applied automatically**. A user who wants these can adopt them
manually (e.g. `git config --global include.path <file>`); Serein only
documents the option.

## GitHub CLI (`gh`)

**Chosen source: Ubuntu's own `gh` package.** Verified live: Ubuntu
26.04 ships `gh` 2.46.0-4 — materially behind GitHub's own apt
repository (reported roughly 50 releases behind at the time of
research). GitHub's official repo (`cli.github.com/packages`) is the
more current source, but adding it means introducing a new,
non-Ubuntu, non-default apt source — a bigger default footprint than
the package-minimalism principle this project applies elsewhere
justifies without a concrete need. Ubuntu's package is fully
functional for standard `gh` workflows (PR/issue management,
auth, releases); the version gap is a real, documented trade-off, not a
hidden one.

**If a user needs GitHub's newest `gh` features**, adding
`cli.github.com`'s own repo is a reasonable manual choice — documented
here as an option, not automated by Serein.

## Authentication

`gh auth status` is never inspected or stored by Serein. `serein dev
doctor` may report "gh installed" but never inspects or reports
authentication state, tokens, or credentials — Section 29 of the S3
brief's explicit boundary.

## SSH and GPG

`openssh-client` is installed (SSH client only — `openssh-server` is
never installed or enabled). No SSH key is generated, inspected, or
read. `gnupg` is installed for the signing-tooling ecosystem Git
integrates with, but no key is auto-created and no commit-signing
configuration is applied automatically.
