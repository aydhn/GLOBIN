# ADR-0040 — Evidence records every gate, and its schema version is a compatibility contract

## Status

Accepted — Phase 011.

**Date:** 2026-08-15

## Context

Phase 010 delivered `tools/quality/evidence/` under
[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md), as
tooling rather than phase scope. It recorded one run as JUnit XML, coverage XML
and JSON, a digested manifest and a checksum list.

An audit at Phase 011 found three things it did not record. Ruff's result was
absent, mypy's result was absent, and there was no human-readable coverage at
all: the evidence run passes `--cov-report=` and `summary.py` writes only to
`$GITHUB_STEP_SUMMARY`, so a local run left nothing a person could open. A run
whose suite passed and whose types did not therefore produced a complete-looking
evidence package describing a repository that does not type-check.

Adding them raised two questions the code could not answer by itself.

**The first is about failure.** `tools/quality/runner.py` stops at the first
failing step, and `QUALITY_GATES.md` makes that normative. Applied here it would
mean a run that stopped at Ruff and produced no test evidence — defeating the
command. Running everything and then failing is the opposite convention, in the
same repository, and an unexplained inconsistency is how a rule stops meaning
anything.

**The second is about the manifest.** `manifest.load` refuses a document whose
`schema_version` it does not recognise, and the document is digest-sealed. Adding
a section is therefore not a widening; it is a change that older readers must
refuse. Version 1 also carried `test_gate_passed` and `coverage_gate_passed`
inside `run`, which the new section would duplicate.

## Decision

**1. The evidence gate records five gates: tests, coverage, lint, format and
typing.** Each writes its result, and the two tool gates write their findings as
`lint-ruff.json`, `format-ruff.json` and `typing-mypy.json`.

**2. Every gate runs, and the verdict is given afterwards.** The gate collects
all five results and then returns the worst. `QUALITY_GATES.md` records this as
the one deliberate exception to fail-fast, with the reason, rather than leaving a
reader to find the inconsistency and guess.

Failure is still never masked: unmeasured outranks failed, failed outranks
passed, and every failing gate is named in the output.

**3. A verdict lives in exactly one place.** `run` records what was measured —
counts, coverage figures, the commit, the interpreter. `gates` records what was
concluded. `test_gate_passed` and `coverage_gate_passed` are gone from `run`,
because two copies of one fact with nothing comparing them is drift rather than a
tripwire ([`SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md)).

**4. `gates` is a mapping, not five more keys.** A reader can enumerate the gates
without knowing their names in advance, and a sixth costs no reader anything.

**5. `SCHEMA_VERSION` becomes 2, and version 1 is refused rather than read.** A
manifest from before this change describes a different set of gates; reading it
as though it described this set would report three gates as never having failed.

**6. Every path a tool reports is normalised to repository-relative POSIX, and a
path that cannot be is not written.** Measured on this machine: `ruff check .
--output-format=json` reports each `filename` as an absolute Windows path
beginning `C:\Users\` and continuing with the account holder's name, *even when
the target given is `.`*. mypy emits repository-relative paths but with Windows
separators, so the same run described on two operating systems would not compare.
A path outside the repository is reduced to a marker and its final component.

**7. Coverage gains a text summary and an HTML tree, and only one of them is
evidence.** `coverage-summary.txt` is digested with everything else. `htmlcov/`
is not: it is a rendering of `coverage.json`, which *is* digested, so
checksumming forty generated pages would add forty lines that prove nothing the
one digest does not already prove.

## Consequences

`python -m tools.quality evidence` now starts six children rather than three and
takes correspondingly longer. It remains outside `fast` and `full`, so no gate
anybody runs in a loop got slower.

The CI artifact grows by the HTML tree. Its retention is unchanged at thirty days
and its upload still runs on `always()`.

A reader with an old manifest gets a refusal naming the version rather than a
partial answer. That is the intended behaviour and the reason the version sits
inside the digested payload.

Ruff and mypy join `_EVIDENCE.modules`, so a machine without either now reports a
missing tool — exit `127` — instead of an unmeasured gate. That is
`QUALITY_GATES.md`'s existing distinction, applied to two more tools.

## Alternatives Considered

**Leave the evidence gate as Phase 010 shipped it.** The most conservative
reading, and defensible: the gate already recorded the thing hardest to
reconstruct. Rejected because "the evidence package" that silently omits two of
the four gates `full` runs is the kind of near-complete artefact that gets
trusted for what it does not say.

**Add lint and typing to `full` instead.** They are already in `full`. The gap
was never that they do not run; it is that nothing records what they found.

**Keep fail-fast and run the tools before the suite.** Consistent with
`runner.py`, and it would mean a lint failure produced no test evidence — the
exact outcome that makes the command worth having. It also inverts the priority:
the suite is the expensive, informative gate, and gating it behind a formatter is
a poor trade.

**Widen the schema without bumping the version,** since a reader could treat the
new section as optional. Rejected: `load` recomputes the digest and checks the
version precisely so that a document cannot be partly understood, and an optional
section is one a reader silently gets wrong.

**Checksum the HTML tree as well.** Complete, and forty lines of digest over
generated pages whose content includes the coverage version. It would make the
checksum file harder to read while proving nothing about the numbers, which are
in `coverage.json`.

**Drop the HTML tree and keep only the text summary.** Genuinely tempting:
`show_missing` is on, so the text carries the missing line numbers as well as the
percentages, in one small deterministic file. Kept both because the line-by-line
view is what somebody actually opens when coverage falls, and the cost is one
command and a directory nothing else depends on.

## Risks and Trade-offs

The characteristic failure is a sixth gate added to `gates` without a reader
being taught to expect it — a dashboard or a later phase's tooling that
enumerates five names. The mapping shape is the countermeasure, and the schema
version is the backstop.

The second risk is that normalisation silently stops working: a change to Ruff's
output, or a repository checked out through a symlink or a substituted drive,
could produce a path the prefix match misses. It would then be written verbatim,
which is the leak. Three things stand in the way — the normaliser refuses to emit
anything with a drive letter or a leading slash, `redaction.scan` reads every
produced file before verification passes, and
`test_no_normalised_path_can_still_be_absolute` asserts the property directly
rather than by example.

The third is that collect-all becomes a precedent, and the next gate is written
that way because this one was. The countermeasure is that `QUALITY_GATES.md`
names it as the one exception and says what makes it one: a command whose purpose
is to produce a record of every gate cannot stop at the first.

## References

- [`docs/engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md)
- [`docs/research/phase_011_sources.md`](../research/phase_011_sources.md)
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md), the
  six conditions this addition is made under
- [ADR-0019](0019-single-quality-entrypoint.md)
- [ADR-0020](0020-verification-only-continuous-integration.md)

## Supersedes

None.

## Superseded By

None.
