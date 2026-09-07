# Focus Domain Model

## Targets vs. domains

```python
FOCUS_TARGETS = ("balanced", "dev", "ai", "cyber", "private")   # what you can request
FOCUS_DOMAINS = ("dev", "ai", "cyber", "private")                # what gets a role
```

`serein focus plan <target>` accepts any of the five targets.
`balanced` produces `primary_domain=None` and every domain in a
non-primary state - it is a target, never a domain competing for
PRIMARY.

## Domain states (Section 6)

```python
DOMAIN_STATES = ("primary", "secondary", "idle", "off")
```

`SUSPENDED` is not modeled - S6.5 has no runtime layer to observe
actual process suspension, so exposing that state would imply an
observed fact nothing here observes.

## Canonical role table (Section 45-48)

For a non-balanced target, the requested domain is `primary`; the
other three follow this table:

| Target    | dev       | ai        | cyber   | private |
|-----------|-----------|-----------|---------|---------|
| `dev`     | primary   | secondary | idle    | off     |
| `ai`      | secondary | primary   | idle    | off     |
| `cyber`   | secondary | idle      | primary | off     |
| `private` | secondary | secondary | idle    | primary |

`private`'s row differs deliberately (Section 48): both `dev` and `ai`
stay `secondary` rather than one of them going `idle`, since neither
is inherently more relevant to a privacy-primary session than the
other, and `cyber` is `idle` (specialized/offensive tooling has no
natural place running alongside a privacy-focused session).

For `balanced` (Section 44), every domain is `secondary` unless its
own readiness is `"blocked"`, in which case it is `off` - balanced
never aggressively quiesces a domain, it simply grants none of them
elevated preference.

## The one-primary invariant, formally

```
0 <= count(role == "primary") <= 1
```

`policy.evaluate_domain_roles(target, evidence)` builds this by
construction - it is structurally impossible for two `DomainRole`
entries to both be `"primary"` in the same call, since only the
literal `target == domain` branch ever assigns it. Verified directly:

```
tests/test_focus.py::TestOnePrimaryInvariant
serein focus doctor -> focus_one_primary_invariant check
```

## Domain readiness (Section 76-80) - separate from focus state

A domain's `DOMAIN_STATE` (primary/secondary/idle/off) is about focus
*preference*; its `readiness` (`available`/`limited`/`blocked`/
`unknown`) is about whether the domain can be *realized at all* right
now, entirely independent of whether it is the current target:

- **dev** (Section 80): `available` once any language toolchain (uv,
  fnm, rustup, Go, C/C++) is confirmed installed (S3 evidence);
  `limited` otherwise - basic shell/Git tooling remains usable even
  with zero toolchains, so dev is never `blocked`.
- **ai** (Section 78): `available` once a GPU-backed PyTorch build is
  usable, *or* CPU-only PyTorch/a local runtime (Ollama/llama.cpp) is
  usable (S4 evidence) - a discrete GPU is never required for
  availability. `limited` otherwise, never `blocked` for missing CUDA
  alone.
- **cyber** (Section 79): `available` once the isolated toolbox is
  installed or VM isolation is usable (S5 evidence); `limited`
  otherwise - host-tier diagnostics remain usable without either.
- **private** (Section 42/77, corrected by S6.5R Corrective D): `available`
  only once a *complete* private-browsing/isolation boundary is
  confirmed usable - `private_workspace.usable`, `whonix_vm.usable`, or
  `tor_browser.usable` is `True` (S6 evidence). **A usable Tor *client*
  alone is deliberately insufficient** - S6 itself keeps "Tor client
  usable" genuinely separate from "application routed via Tor"/
  "private workspace usable"/"Whonix usable"
  (`docs/veil/threat-model.md`), and an earlier S6.5 pass had
  incorrectly re-collapsed that distinction by treating
  `tor_client.usable=True` as sufficient for `"available"`. The
  corrected chain:

  ```
  complete boundary usable (workspace/whonix/browser)  -> "available"
  Tor client usable, no complete boundary usable          -> "limited"
  some mechanism merely installed, nothing usable            -> "limited"
  nothing present at all                                       -> "blocked"
  ```

  `serein focus doctor`'s `focus_private_readiness_not_tor_only` check
  re-verifies live that Tor client usability alone never upgrades
  readiness to `"available"`.

## Domain readiness vocabulary is mechanism-specific, never marketing (Section 77)

Reason text for `private` cites concrete S6 evidence ("Tor client is
confirmed usable", "No usable Tor client, Tor Browser, or Whonix
readiness detected") - never "high anonymity"/"fully anonymous"/"100%
private". Regression-tested directly
(`tests/test_focus.py::TestDomainReadiness::test_private_reason_uses_mechanism_terms_not_marketing`).
