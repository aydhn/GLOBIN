# ADR-0042 — One aggregate check decides a run, and the artifact digest lives outside the artifact

## Status

Accepted — Phase 012.

**Date:** 2026-08-15

## Context

The brief supplied for Phase 012 described CI quality-gate aggregation. `ROADMAP.md`
assigns Phase 012 to *Serialization and Persistence Contracts*, which
[ADR-0041](0041-serialization-is-exact-or-refused-and-a-version-is-refused-when-unknown.md)
delivers. This is the **eighth** time a brief has collided with the roadmap, and
it was resolved the way the sixth and seventh were: the phase's own scope is
delivered in full, and the part of the brief nothing in the programme owns is
added as tooling under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md).

An audit found most of the brief already delivered. `tools/quality/evidence`
writes JUnit XML, coverage in four forms, a schema-versioned digested manifest
with per-gate verdicts, SHA-256 checksums and a `$GITHUB_STEP_SUMMARY` summary;
the workflow pins every action to a commit SHA, declares `contents: read`, and
uploads on `always()` with `retention-days: 30` and `if-no-files-found: error`.

Two things were genuinely missing, and both are about the *run* rather than the
tree.

**Nothing aggregated the jobs.** The workflow presented six status checks and no
single one to require. Two of them are named `Quality (Python 3.12)` and
`Quality (Python 3.14)` — a matrix job's check name carries its matrix value — so
a branch protection rule naming them breaks the day Phase 018 changes the
interpreter list.

**Nothing noticed a job that did not run.** GitHub skips a job whose dependency
failed, and a skipped required check is not reported to branch protection as a
failing one. A rule trusting the check view could be satisfied by a run in which
every job it depended on had failed.

Separately, `actions/upload-artifact` publishes an `artifact-digest` output — the
SHA-256 of the uploaded bundle — which nothing captured. Capturing it raises a
question with an impossible answer if asked carelessly: an artifact cannot
contain its own digest, because the digest is computed from the finished artifact.

## Decision

**1. One aggregate job, named `Quality gate`, is the check to require on
`master`.** It depends on every other job, and its name carries no operating
system, no interpreter version and no matrix value, so it survives changes to all
three. The name is declared in `[tool.globin.workflow]` as well as in the
workflow, and a contract test compares them.

**2. It runs when something upstream did not.** `if: ${{ !cancelled() }}` rather
than the default, because a job with `needs` is otherwise skipped after a
dependency fails — which is precisely the case the check exists to catch.
`always()` was rejected: with `cancel-in-progress: true`, every push cancels the
run before it, so `always()` would spend a runner and post a confusing failing
check on every superseded run.

**3. Success requires every job to have *reported* success.** The declared
`required_jobs` list is checked against what the `needs` context actually
contains. A required job absent from the context is unmeasured, not omitted — a
result built only from what reported would simply not mention a job that vanished,
leaving every entry present and passing.

**4. Every unfamiliar answer is unmeasured, and unmeasured is never a pass.**
GitHub documents four job results; a fifth would be a platform change nobody here
had read about. `cancelled`, `skipped`, absent and unrecognised all become
unmeasured, which `tools/quality/execution/plan.py` already makes outrank a
failure. Exit codes follow the evidence gate's four: `0`, `1`, `2` for usage,
`3` for unmeasured.

**5. The verdict is computed in Python, not in YAML.** The workflow supplies
`toJSON(needs)` through the environment and runs one command. Quality logic
spread across job-level `if:` expressions is untestable, and this repository's
rule since [ADR-0019](0019-single-quality-entrypoint.md) is that a check is a
name in the command table.

**6. The aggregate re-verifies the published bytes.** It downloads the evidence
artifact and runs the same `python -m tools.quality.evidence verify` the evidence
job ran. The bytes differ — they have been through an upload and a download — so
a bundle corrupted in transit is caught rather than trusted because a job said it
was fine. It also refuses a manifest recording fewer gates than the evidence run
produces, which is what an evidence run that crashed halfway leaves behind.

**7. File digests live inside the artifact; the artifact's digest lives outside
it.** `checksums.sha256` is computed before upload and covers every file in the
bundle. The bundle's own SHA-256 is computed by GitHub as the upload completes,
published as a job output, recorded in `aggregate-quality.json` and shown in the
summary. Neither layer contains the other, and the impossible design — a manifest
inside the artifact stating the artifact's digest — is ruled out by construction
rather than by remembering not to attempt it.

**8. The aggregate is a second artifact, not a file in the first.**
`aggregate-quality.json` records the evidence bundle's digest, so writing it into
that bundle would make the bundle's digest depend on a value derived from the
bundle. It is uploaded as `quality-gate-verdict`, with the same thirty-day
retention.

**9. Branch protection is not configured by this phase.** It is a repository
setting in a different control plane, and no file in this tree can make a check
required. `QUALITY_GATES.md` names the check and says plainly that until somebody
sets it in the repository's settings, the check is informative rather than
blocking.

## ADR-0032 compliance

All six conditions, stated rather than implied.

1. **It displaces no phase.** Every one of the 320 roadmap rows was read: none
   names CI aggregation, required status checks or artifact provenance. Phase 004
   owned "a verification-only CI workflow" and is complete.
2. **It defers nothing.** ADR-0041's serialization contracts ship complete in the
   same commit.
3. **It adds no dependency.** Standard library only; the workflow is still parsed
   as text by the contract tests rather than with a YAML library, and the `dev`
   extra is unchanged at six names.
4. **It adds no runtime capability.** Nothing under `src/globin/` changed because
   of this. The serialization modules in the same commit are Phase 012's own
   scope, not this record's.
5. **It only reports.** It writes nothing outside the ignored `.globin/` run
   directory, and `aggregate` is in neither `fast` nor `full`.
6. **It is documented and tested to the same standard.** A row in the command
   table, a row and a section in `QUALITY_GATES.md`, tests at the unit, contract
   and integration levels, and the branch coverage floor held.

## Consequences

`master` has one check worth requiring, and a run in which a required job silently
did not happen cannot produce it. Somebody still has to turn on the branch
protection rule; this phase makes that action meaningful rather than performing it.

The workflow gained a sixth job and a second artifact. The job installs no tools
and reads two files, so it costs a checkout and an interpreter.

`aggregate-quality.json` is a new machine-readable document with a schema version
of its own, and the rule ADR-0041 states applies to it: a reader refuses a version
it does not implement rather than guessing.

The `required_jobs` list is now a thing to maintain. That is deliberate — it is
what makes a deleted job a failure rather than a silence — and the contract test
comparing it against the workflow is what stops it rotting.

## Alternatives Considered

**Require all six existing checks instead of adding a seventh.** No new job, no
new artifact. Rejected because two of the six carry an interpreter version in
their name, so Phase 018 would break the rule, and because requiring six checks
still does not notice a job that was never declared.

**Have the evidence job publish its verdict as a job output and trust it.**
Cheaper, and no `download-artifact`. Rejected because it is the job reporting on
itself. Re-reading the published bundle costs one download and checks the thing
that was actually kept.

**Put the aggregation logic in the workflow's `if:` expressions.** Idiomatic
GitHub, and what most repositories do. Rejected because it cannot be unit-tested,
cannot be run locally, and would put the definition of "passed" somewhere other
than the command table ADR-0019 made the single source.

**Use `always()` on the aggregate job.** Simpler to reason about and the more
common spelling. Rejected for the concrete cost noted in decision 2: with
`cancel-in-progress: true` every push cancels its predecessor, so the aggregate
would run on runs nobody will merge and post failing checks about them.

**Write the artifact digest into the evidence manifest.** What the brief's
wording invited. It is not merely awkward but impossible — the digest is computed
from the finished artifact, so a manifest inside it stating the digest would have
to contain a hash of itself. Decision 7 is the reason this record exists in the
form it does.

## Risks and Trade-offs

The characteristic failure is that `required_jobs` and the workflow drift in a way
the contract test does not catch. The test compares job *keys*, and a job key can
survive while the work inside it is gutted. Nothing here defends against a job
that runs `exit 0` — though a separate contract test already forbids that literal
— and nothing can defend against a job whose command was quietly narrowed. The
evidence re-verification is the mitigation: a narrowed suite shows up as different
counts in a manifest somebody can read.

The aggregate depends on the evidence job for its gate results, so the two are
coupled: an evidence run that fails to produce a manifest makes the aggregate
unmeasured even when every job passed. That is the intended direction — it fails
closed — but it does mean a flake in one job can fail the required check for a
tree that was fine. The alternative was to let a missing manifest pass, which is
the failure this whole record exists to prevent.

Decision 6 re-runs verification on a second machine. If the two ever disagree,
the run fails without saying which machine was wrong. That is acceptable because
disagreement is itself the finding: the bundle was supposed to be identical.

## References

- [`docs/engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md)
- [ADR-0019](0019-single-quality-entrypoint.md)
- [ADR-0020](0020-verification-only-continuous-integration.md)
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md)
- [ADR-0036](0036-test-execution-is-sharded-by-a-stable-digest-not-by-a-plugin.md), for the verdict vocabulary reused here
- [ADR-0040](0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md)
- [`docs/research/phase_012_sources.md`](../research/phase_012_sources.md)

## Supersedes

None.

## Superseded By

None.
