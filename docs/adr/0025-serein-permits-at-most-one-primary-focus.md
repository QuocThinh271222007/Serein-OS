# ADR-0025: Serein Permits At Most One PRIMARY Focus

## Status

Accepted

## Context

Serein now spans four professional domains (development, AI,
cybersecurity, privacy) that each carry real resource-preference
implications - a development-heavy session wants compiler/IDE
responsiveness, an AI session wants GPU/memory headroom, a cyber
session wants toolbox/VM budget, a privacy session wants isolation
correctness over throughput. Without a formal concept of "what the
user currently cares most about", any future resource-allocation
mechanism would have to guess, or would need every domain to compete
unstructured for the same pool - a recipe for unpredictable behavior
and, eventually, a system that silently favors whichever domain was
loudest.

## Decision

- At most one domain may hold the `"primary"` role at any moment:
  `0 <= count(primary) <= 1`, enforced by construction in
  `policy.evaluate_domain_roles()` - a professional target assigns
  exactly its own domain `primary`; `"balanced"` assigns none.
- `PRIMARY` never means `EXCLUSIVE` - other domains remain
  `secondary`/`idle`/`off`, never removed from the model, and ordinary
  interactive applications (browser, editor, terminal, desktop) are
  never implied to stop regardless of which domain is primary.
- `"balanced"` is a distinct, fifth target meaning "no domain owns
  primary preference" - it is never modeled as a domain itself, and it
  never produces a `primary_domain`.
- The invariant is checked live, not only in unit tests:
  `serein focus doctor`'s `focus_one_primary_invariant` check runs
  `build_focus_policy()` for every one of the five targets and fails
  loudly if any produces more or fewer primaries than expected.

## Consequences

- Every future resource-allocation mechanism (a systemd slice
  hierarchy, a cgroup weighting scheme, a GPU lease negotiator) has one
  unambiguous question to answer first - "who is primary, if anyone" -
  rather than needing its own conflict-resolution policy from scratch.
- A caller can trust `FocusPolicy.primary_domain` as the single source
  of truth for "what does the user currently care about most" without
  needing to re-derive it from domain roles.
- The invariant is cheap to verify (a single doctor check, five policy
  computations) and is re-verified on every CI run.

## Alternatives considered

**Allow multiple simultaneous primaries with a priority order between
them.** Rejected - this reintroduces the exact ambiguity a single
PRIMARY concept exists to eliminate; "AI is primary, but so is Cyber,
except Cyber wins on GPU but AI wins on memory" is not a clearer model
than one primary domain.

**Model `balanced` as its own primary domain ("balanced is primary").**
Rejected explicitly per the S6.5 brief (Section 5) - `balanced` means
*no* domain owns preference, not that a fifth "balanced" workload
becomes the preferred one.
