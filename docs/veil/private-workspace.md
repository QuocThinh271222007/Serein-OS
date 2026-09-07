# Private Workspace Model

## Candidate mechanisms (Section 13)

```
A. isolated browser profile + SOCKS5h        (preferred - least privilege)
B. rootless network namespace/container + Tor proxy
C. dedicated namespace managed by a future Apply engine
```

S6 documents all three as candidates; it implements none of them.
Mechanism A needs no elevated privilege and no container runtime, so
it is always the reported `mechanism` even in a nested-container
environment; mechanism B is additionally noted when the environment is
not itself already a nested container (mirroring S5's
`container_capability_available` reasoning).

## Container isolation is not automatically privacy isolation (Section 14-15)

A generic Podman/Distrobox container shares the host kernel and may
inherit DNS behavior, host services, metadata, filesystem integration,
clipboard, and display/session integration - none of that is Veil-grade
isolation by default. Distrobox in particular is *intentionally*
tightly host-integrated (that is its whole point for S3's development-
tooling use case) - it must never be treated as the strongest privacy
boundary Serein can offer. Whonix (`docs/veil/whonix.md`) remains the
strong boundary; an ordinary toolbox container is, at best, a
documented-limitations candidate for mechanism B above.

## `VeilWorkspaceReadiness` - the single canonical verdict (Section 55)

`src/serein/veil/workspace.py`'s `evaluate_workspace_readiness()` is
the one place "is a private workspace usable" is computed -
`capabilities.py`, `planner.py`, `status.py`, and `doctor.py` all
consume its result rather than each deriving it independently (the
exact discipline S5R's VM-readiness corrective established, applied
here from the start rather than retrofitted).

```
tor.usable is False  -> usable=False, privacy_level="none"
tor.usable is None    -> usable=None,  privacy_level="none"
tor.usable is True      -> usable=None,  privacy_level="tor_application"
                            (never "isolated_workspace"/"whonix" - no
                            boundary has actually been created)
```

`configured` is always `False` - S6 has no Apply engine, so nothing is
ever actually built (Section 78-79). `usable` can therefore never
legitimately be `True` in the current implementation: Section 57
explicitly forbids reporting `usable=true` merely because Tor and Tor
Browser are both installed, and since nothing is ever configured
either, there is nothing for "usable" to affirm yet.

## Privacy levels are mechanism names, not marketing (Section 56)

```python
PRIVACY_LEVELS = ("none", "tor_application", "isolated_workspace", "whonix")
```

Never "low anonymity"/"high anonymity" - a machine-readable mechanism
name, never a confidence claim
(`tests/test_veil.py::TestInvariants::test_privacy_levels_are_mechanism_names_not_marketing_confidence`).

## Browser profile isolation (Section 16) - planned, never created

A future isolated profile would use a separate profile directory, its
own cookie/storage state, no shared history, and no shared extensions
by default. S6 only plans this
(`workspace.private_profile` in `planner.py`, `BLOCKED` until Tor is
usable, `APPLY` afterward as a future-Apply placeholder) - it never
creates a profile and never touches an existing browser profile.
