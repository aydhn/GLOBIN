# ADR-0045 — A platform capability is a recorded state, never a pass

## Status

Accepted — Phase 014.

## Context

Half the controls Phase 014 is asked to deliver are not this repository's to
implement. CodeQL, secret scanning, push protection, dependency review, artifact
attestations and rulesets are GitHub features. They are governed by an account
plan and a visibility setting, in a control plane no file in this tree can reach.

A gate has to say something about them, and the tempting options are both wrong.
Reporting them as passing because they could not be checked is a lie the gate
tells on every run. Omitting them leaves a reader to infer an answer, which is
the same lie with deniability.

The problem is sharper than it looks, because "unavailable" is not one thing.
Probed against this repository on 2026-08-15, while it was private on a personal
Free plan:

```
GET /repos/aydhn/GLOBIN/rulesets
  403 "Upgrade to GitHub Pro or make this repository public to enable this feature."

GET /repos/aydhn/GLOBIN/code-scanning/analyses
  403 "This API operation needs the \"admin:repo_hook\" scope."
```

Two `403`s. The first is a plan ceiling and no commit, scope or effort changes
it. The second is a token that was not asked for enough, and the remedy is one
`gh auth refresh`. Collapsing both into "unavailable" would send somebody to buy
a subscription they did not need.

## Decision

**A capability is recorded as one of seven states, with the evidence that
established it.**

| State | Meaning |
|---|---|
| `PASS` | Checked, and enabled. |
| `FAIL` | Checked, available, not enabled. The only state that is somebody's fault. |
| `UNAVAILABLE_BY_PLAN` | This account or visibility cannot have it. |
| `UNAVAILABLE_BY_PERMISSION` | The credential used may not ask. |
| `NOT_APPLICABLE` | The question does not arise here. |
| `NOT_PROBED` | Nothing asked. |
| `ERROR` | The probe itself failed. |

**`UNAVAILABLE` is never reduced to `PASS`.** An overall `PASS` while a control
is unavailable is permitted only where that control is marked `recorded` rather
than `required`, *and* a local compensating control passed. The pairings are
explicit: content secret scanning compensates for GitHub secret scanning,
`pip-audit` compensates for Dependabot alerts, the pin gate compensates for
dependency review. Where there is no local compensation, the control is
`required` and being off is a `FAIL`.

**The classification is pure and the probing is not.**
`tools/quality/supply/capability.py` maps an HTTP status and a message to a state
in a function tested from literals, offline. Only `probe` starts `gh`.
[ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) makes the
suite offline, and a test that needed the network would fail on an aeroplane.

**Plan and permission are distinguished by the message text**, because GitHub
distinguishes them in prose rather than in the status code. Both marker sets come
from responses actually observed against this repository, recorded in
`docs/research/phase_014_sources.md`.

**An unrecognised `404` is `FAIL`, not `UNAVAILABLE`.** `404` means both "off"
and "no such thing", and assuming absence would let a control that is merely
switched off pass as one nobody could have.

**A control that the API says it enabled and then did not is
`UNAVAILABLE_BY_PLAN`, by a recorded fact rather than a guess.**
`secret_scanning_non_provider_patterns` accepts a `PATCH`, returns `200`, and
remains `disabled`. Nothing in the response says so. That was established by hand,
twice, and is recorded in the control's own `unavailable_reason` — otherwise it
would report a permanent `FAIL` nobody can fix, which trains people to ignore the
manifest.

## Consequences

- The manifest's `capability` section is the one part that legitimately differs
  between a local run and a CI run, because CI asks with the run's own token. That
  is a fact about who asked, and recording it is better than hiding it.
- `code_scanning` asks for *analyses*, not for the default-setup configuration.
  The configuration endpoint returns `200` with `"state": "not-configured"` on a
  repository where nothing analyses anything — a body that classifies as a pass
  while meaning the opposite.
- `code_scanning` is `recorded` rather than `required` for a sequencing reason:
  the commit that adds the CodeQL workflow is judged before that workflow has run,
  so requiring an analysis would fail the commit introducing analysis.
- Going public flipped six controls from `UNAVAILABLE_BY_PLAN` to available in one
  action, which is the clearest possible demonstration that these states describe
  a setting rather than a defect. See [ADR-0046](0046-the-repository-is-public-and-that-changes-the-threat-model.md).

## Alternatives Considered

**A boolean per control.** Rejected — it is exactly the conflation this record
exists to prevent, and it is what a naive implementation produces.

**Omit unavailable controls from the manifest.** Rejected. An absent key and a
recorded `UNAVAILABLE` read very differently six months later, and only one of
them says anything.

**Hard-code the known plan limits instead of probing.** Rejected: it would have
been wrong within the hour. Every limit recorded while this repository was private
became false the moment its visibility changed.

**Fail the gate on any unavailable control.** Rejected. Nobody can fix a plan
ceiling from a commit, and a gate that fails for something no commit can change
is a gate people learn to ignore.

## Risks and Trade-offs

**The probe needs the network and a credential.** Without either, every state is
`NOT_PROBED`, which is honest but uninformative. That is why `NOT_PROBED` is not
a pass and why the mandatory checks are all local.

**A capability's state can change without a commit.** Somebody can switch secret
scanning off in a settings page and no diff records it. The next run records
`FAIL` and the gate fails, which is the best a repository can do about a control
it does not own.

**The marker lists are text matching against another organisation's prose.**
GitHub can reword a message and turn an `UNAVAILABLE_BY_PLAN` into a `FAIL`. That
direction is the safe one — it over-reports a problem rather than hiding one — and
the alternative is trusting a status code that does not carry the distinction.

## References

- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — which states may count as a pass
- [`../research/phase_014_sources.md`](../research/phase_014_sources.md) — the probes and their responses
- [ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) — why the probing is not in the suite
- [ADR-0044](0044-dependency-review-is-a-written-process-with-a-generated-inventory.md) — the local half
- [ADR-0046](0046-the-repository-is-public-and-that-changes-the-threat-model.md) — what changed the answers

## Supersedes

None.

## Superseded By

None.
