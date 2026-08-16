# ADR-0066 — A stack may be published once its paths are reduced and it stays out of a bundle

## Status

Accepted — Phase 025.

**Date:** 2026-08-17

## Context

Phase 024 refused to put thread stacks anywhere in the health surface, and argued
it rather than assuming it.
[`../../src/globin/domain/health.py`](../../src/globin/domain/health.py) states the
refusal on `ThreadDescription`: a stack trace names functions, files and line
numbers, *and a thread parked inside a credential read would say so*. It pointed at
Phase 023's `faulthandler`, which writes stacks deliberately, into a file that is
not the log.

Phase 025 needs stacks. A confirmed stall is precisely the moment somebody wants to
know where the process is parked, and
[`../research/phase_025_sources.md`](../research/phase_025_sources.md) S-06 records
that CPython documents `sys._current_frames` for exactly this — *"most useful for
debugging deadlock: this function does not require the deadlocked threads'
cooperation"*.

So Phase 024's refusal has to be either overridden or answered. Overriding an
argued decision because a later phase found it inconvenient is how a codebase stops
meaning what it says.

## Decision

**1. The refusal is answered on its own terms, and its terms are about travel.**
Phase 024's concern is that a health snapshot goes into a support bundle and from
there to whoever an operator sends it to. That concern is correct and unchanged.
The response is therefore not "stacks are safe after all" but **a different
destination**:

- A stall incident is published to `state/watchdog.json` in the user-local runtime
  tree.
- It is **not** added to `bundle_candidates`, and a contract test asserts its
  absence rather than trusting this paragraph.
- What does reach the health snapshot is `WatchdogSummary`: counts, a state name,
  and component names an operator chose. No path, no function, no line, no
  timestamp.

**2. Frame filenames are reduced through `relative_location`, which already
exists.** Phase 024 wrote it for `AllocationSite.location` — a source location
pulled out of a traceback, the same class of data — and it maps a path under the
package to `globin/...`, one under the standard library to `stdlib/...`, and
anything else to its bare filename, *because a path that could not be attributed is
a path whose directories are somebody's private business*. It was made public in
this phase because it acquired a second caller; it was not reimplemented.

**3. `RecordedPath` was considered for this and rejected.** It is the repository's
type for writing a path down safely, and for a path outside the tree it yields a
fingerprint only. In a manifest that is right — the question there is *is this the
same root as last time*. In a stack the question is *where is it stuck*, and a
fingerprint cannot answer it. Using it would have paid the full cost of capture for
evidence nobody could read.

**4. No locals, ever, and that is the leak that actually matters.**
`sys._current_frames` hands out **live frame objects**. A frame's `f_locals` holds
the values a credential-reading function was working with, not merely the name of
the function reading them — which is a strictly larger exposure than the one Phase
024 was guarding against. Three rules follow: summaries are extracted with
`traceback.extract_stack` and nothing is ever asked to capture locals; no `repr` is
called on anything reached from a frame; and the mapping is dropped in the same call
that read it.

**5. `domain/health.py`'s absolute wording is corrected in this diff.** It said
"No stack" without qualification. It now says what remains true — no stack in the
*health* surface — and points here. A document left asserting something the code no
longer does is the failure [ADR-0010](0010-living-documentation-responsibilities.md)
names.

## Consequences

- `RuntimeHealthSnapshot` gains a `watchdog` field with a default, so
  `HEALTH_SCHEMA_VERSION` stays 1 and every existing reader is unaffected.
- `_relative_location` becomes `relative_location`, with a docstring naming both
  callers.
- The stall incident is the first GLOBIN document that is deliberately excluded from
  a support bundle, which makes "is this a bundle candidate" a question future
  documents have to answer rather than inherit.
- An operator who wants to send stall evidence to somebody else must do it
  knowingly, by attaching a file, rather than by running `diagnostics bundle`.

## Alternatives Considered

**`faulthandler` only, with no Python-side frames.** Simplest, opens no new
redaction surface, and touches Phase 024's decision not at all. Rejected by the
owner when the choice was put: the incident manifest would carry no machine-readable
thread evidence, only a pointer to an append-only text file shared with the process
fault hooks.

**Sanitise frame filenames through `RecordedPath`.** Rejected — see decision 3.

**Put the incident in the bundle and redact harder.** Rejected: redaction matches
field names, and a stack's risk is in its values. The destination is the control
that actually works.

**Override Phase 024's refusal and publish stacks in the health snapshot.**
Rejected: the argument that snapshot travels is still true, and nothing in this
phase weakens it.

## Risks and Trade-offs

**The characteristic failure mode is that the bundle exclusion is quietly
reversed.** A later phase adds `state/*.json` to `bundle_candidates` as a
convenience, and stall evidence starts travelling. **The observable signal** is the
contract test asserting `watchdog.json`'s absence being edited or deleted; that test
is the whole enforcement, and a change to it should be read as a change to this
decision.

**A second is that `relative_location` is not a redactor and is not one here
either.** It reduces paths. A function *name* that embarrasses somebody, or a
component name an operator typed a token into, still travels. That limit is stated
in [`../engineering/RUNTIME_WATCHDOG.md`](../engineering/RUNTIME_WATCHDOG.md) rather
than implied.

**A third is the auditing event.** `sys._current_frames` raises one, so a host with
an audit hook installed will see the watchdog every time it captures. That is
correct behaviour and worth knowing before somebody reports it as unexpected.

## References

- [`../../src/globin/domain/health.py`](../../src/globin/domain/health.py) — the
  Phase 024 refusal this answers.
- [ADR-0063](0063-a-support-bundle-is-allowlist-first-self-validating-and-atomically-published.md)
  — the allowlist this document stays out of.
- [`../research/phase_025_sources.md`](../research/phase_025_sources.md) — S-06 and
  S-08 on what frames are for and what they cannot be trusted to say.
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)
  — the redaction contract this does not weaken.

## Supersedes

None.

## Superseded By

None.
