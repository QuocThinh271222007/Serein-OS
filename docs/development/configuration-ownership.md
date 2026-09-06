# Development Configuration Ownership

The same "critical requirement" discipline S1 established for the
desktop layer applies here: Serein must never silently overwrite a
user's existing development configuration.

## What Serein ships (templates only, never auto-applied)

| Resource | Repo path | Target | Owner |
|---|---|---|---|
| Zed settings template | `development/zed/settings.json` | `~/.config/zed/settings.json` | first-login-user (applied only if no existing file — S1's Look-and-Feel model) |
| Git recommended defaults | `development/git/recommended.gitconfig` | none — user opt-in only | user-opt-in (never written automatically) |

`DEVELOPMENT_CONFIG_VERSION = 1` (`src/serein/development/models.py`) is
independent of `serein.__version__`, following the exact pattern
`DESKTOP_CONFIG_VERSION`/S2's `PLAN_SCHEMA_VERSION` established — bumped
only when the shape of a shipped resource changes in a way a future
migration needs to know about.

## What Serein never touches

```
~/.gitconfig              (user.name, user.email, signing keys, credential helpers)
~/.config/zed/settings.json  (once it exists, ever again)
~/.nvm, ~/.pyenv, ~/miniconda3, ~/anaconda3  (existing user tooling - detected, not modified)
SSH keys, GPG keys
shell rc files (~/.bashrc, ~/.zshrc, etc.)
```

## Why the Zed template's "first-login-only" model is safe to claim now

S1R directly validated the exact upstream mechanism this depends on
(KDE's Look-and-Feel KPackage applying only when no user layout already
exists). Zed's own settings-file behavior — reading `~/.config/zed/
settings.json` if present, using its own defaults otherwise — is
standard, well-documented application behavior, not a novel claim; a
future Apply step would still need to explicitly check
`~/.config/zed/settings.json`'s absence before writing the template,
exactly as the desktop layer's installer would need to check for an
existing Plasma layout. No Apply step exists yet in S3 to have
implemented this check — it is a design commitment, not a proven one
(see docs/development/known-limitations.md).

## Reversibility

Both shipped resources are plain files a user can delete or ignore.
Neither resource, if ever applied, would remove or modify anything that
predated Serein — consistent with S1/S2's reversibility model.
