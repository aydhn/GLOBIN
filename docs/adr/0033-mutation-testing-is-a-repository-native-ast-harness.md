# ADR-0033 — Mutation testing is a repository-native `ast` harness gated by a committed survivor set

## Status

Accepted — Phase 008.

**Date:** 2026-08-14

## Context

Branch coverage says a line ran and both arms of its condition were taken. It
cannot say whether anything would have noticed the line being different. A suite
of tests that execute everything and assert almost nothing scores well on
coverage and catches nothing, and `QUALITY_GATES.md` already argues that raising
a coverage number by adding tests that assert nothing is the exact trade this
project refuses. Mutation testing is the measure that notices.

[ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) settles
whether the gate may exist. This settles what it is.

Two facts about the existing tools decided the build-or-adopt question, and both
are recorded in [`docs/research/phase_008_sources.md`](../research/phase_008_sources.md).

- **`mutmut` cannot run here.** `src/mutmut/__main__.py` calls `os.fork()`, which
  Windows does not have; the project's own README states that a Windows user must
  run it inside WSL; its CI matrix is `ubuntu-latest` only, and two issues asking
  for Windows support are open. GLOBIN's declared host and its continuous
  integration are both Windows
  ([ADR-0009](0009-windows-bat-launchers-as-entry-points.md)),
  and `MEMORY.md` records the Windows-only CI matrix as settled.
- **`cosmic-ray` runs anywhere but costs thirteen transitive dependencies**,
  including `aiohttp`, `gitpython` and `sqlalchemy`, in a repository whose
  `dependencies = []` is asserted by a contract test and whose suite installs a
  guard against outbound sockets. It also carries no Python 3.14 classifier, and
  reviewing a dependency of that size is Phase 014's process, which does not
  exist yet.

Condition 3 of ADR-0032 therefore does the choosing: a gate that adds a
dependency is not covered.

## Decision

**1. The harness is `ast` and `subprocess`, in `tools/quality/mutation/`.** It
adds nothing to the toolchain. The package is split by purity — `operators`,
`plan` and `baseline` are pure functions over syntax trees and mappings, `gate`
orchestrates, and `sandbox` is the only module that touches a disk or a process —
because `tools` is measured under branch coverage and a judgement entangled with
a subprocess is a judgement tested once and hoped about.

**2. Six operators, chosen to be subtle.** Comparison swaps, boolean-operator
swaps, `+`/`-` swaps, `not` removal, integer increment and boolean-constant
inversion. A mutant that makes a module explode teaches nothing, because any test
that touches it fails without a single assertion having been read. String
literals are excluded (almost all are docstrings and loosely-matched error
messages, so mutating them produces equivalent mutants in bulk), as are statement
deletion and return-value replacement (too fatal), `not`-insertion (redundant with
comparison swaps) and integer members of an enumeration (guaranteed survivors).

**3. The run works in a copy of the tree, and that copy owns `pyproject.toml`.**
This is the decision the whole design turns on. `pyproject.toml` sets
`pythonpath = ["src", "."]`, and pytest inserts those at `sys.path[0]` resolved
against its rootdir, *after* the interpreter has processed `PYTHONPATH`. A
harness that wrote a mutant to a temporary directory and prepended it to
`PYTHONPATH` would import the real module every time, every mutant would survive,
and the score would be a lie that reads as a finding.

**4. Two control runs precede every verdict.** The unmutated subset must pass, or
there is nothing to measure. Then the target module is replaced by
`raise ImportError` and the subset must *fail* — if it still passes, the sandbox
is not the tree being imported, and the run stops. Decision 3 is thereby checked
on every run rather than assumed.

**5. An exit code is never guessed at.** pytest defines seven. Only `0` and `1`
are verdicts; `5` (nothing collected) and everything else stop the run as
unmeasured. That is the third state `QUALITY_GATES.md` already names: passed,
failed, and not run, with "not run" never reporting as "passed".

**6. Test subsets are declared as file paths, never as `-k` or a marker.** A
mistyped path is caught in the parent before anything launches; a mistyped
selector makes pytest exit 5 having collected nothing, which is the failure
decision 5 exists to refuse.

**7. The gate compares the survivor set, in both directions, and not the score.**
A survivor the baseline does not expect fails. A recorded survivor the run killed
also fails, for the reason `xfail_strict = true` is set: a claim that has stopped
being true is worse than no claim, because somebody will believe it. The total
mutant count is deliberately **not** pinned — adding a branch the tests already
cover produces mutants that die immediately, and failing a build for that would
be friction with nothing behind it.

**8. Nothing writes the baseline.** `tomllib` reads TOML and the standard library
ships no writer, so the harness physically cannot refresh it and does not
pretend to: on disagreement it prints the block it would have described, with
every reason filled by a placeholder that
`tests/contract/test_mutation_contract.py` refuses. Pasting it unread fails the
suite rather than passing the gate.

**9. The gate is in neither `fast` nor `full`, and CI runs it in its own job.**
`fast` promises seconds. `full` runs before every commit and ends in a
coverage-measured pytest run, and nesting a pytest-spawning step inside one is
the re-entrancy decision 3 works to make impossible.

## Consequences

`tools.quality mutation` takes about two minutes for one target of fifty-two
mutants, and grows linearly with what is declared. The first target is
`src/globin/domain/values.py`; adding more is a configuration change and a
baseline entry.

The first run found a real defect in this phase's own tests. The cross-type
comparison test matched `"not supported between instances"`, which a mutated
comparison also produces while naming `Decimal` and `NoneType` instead of the two
value types. Coverage could not have found it: the weakened assertion executed
every line. Tightening it killed eight mutants.

Four survivors are recorded, all the same mutation of the same decorator —
`slots=True` becoming `slots=False`. They are recorded rather than killed because
no other frozen dataclass in the repository asserts its own slotted-ness, and
adding the assertion for these four alone would be a test written to move a
number.

Two lines in the repository are now knowingly uncovered rather than one: the
`if __name__ == "__main__"` guard in each of the two entry points.

## Alternatives Considered

**`mutmut`.** The obvious choice and the one the brief named. It cannot run on
the platform this project targets, which is not a preference to be argued with.

**`mutmut` on a Linux CI runner only.** It would work, and it would mean the
person who has to fix a survivor could never run the gate that reports it. It
also reopens the Windows-only CI decision `MEMORY.md` marks as settled.

**`cosmic-ray`.** Cross-platform, actively maintained, and thirteen dependencies
including an HTTP client, in a repository whose test suite blocks sockets. Barred
by condition 3 of ADR-0032, and by Phase 014 not having happened.

**Pin the mutant count as well as the survivor set.** Stricter, and it would
catch a deleted branch improving the score for the wrong reason. Refused because
adding one covered `if` to a target module would fail the build until somebody
edited a data file, which is friction that teaches people to distrust the gate.

**Score against a floor, as coverage does.** Consistent with `QUALITY_GATES.md`,
and it lets the baseline go stale in the one direction that matters: a gap that
has since been fixed can sit in the exemption list for years, and the file
becomes folklore.

**A `--update` flag.** Every mutation tool has one. It is the mechanism by which
a baseline stops being read.

## Risks and Trade-offs

The characteristic failure is the gate becoming expensive enough to be worked
around: more targets, a slower CI job, and eventually a commit that adds
`continue-on-error`. The observable signal is that line appearing in the workflow,
which a contract test already refuses — so the more likely form is targets
quietly not being added, and the gate measuring one module forever.

The second risk is that `ast.unparse` is not guaranteed to produce identical text
across Python versions. It was verified as a fixed point for all twenty-seven
modules in this tree on 3.14, but the CI matrix runs 3.12 as well. The mutation
job therefore runs on one interpreter, and a baseline recorded against it is
evidence about that interpreter. If the two ever disagree, the symptom is a
mutant count that differs by version, and the answer is to record it as a finding
rather than to loosen the comparison.

The third is that the harness is code this project now maintains. It is about
four hundred statements, covered at 99%, and it does one thing. The signal that
it has grown past its worth is a second reader being unable to follow `gate.py`
in one sitting.

## References

- [`docs/engineering/mutation-baseline.toml`](../engineering/mutation-baseline.toml)
- [`docs/engineering/QUALITY_GATES.md`](../engineering/QUALITY_GATES.md)
- [`docs/research/phase_008_sources.md`](../research/phase_008_sources.md)
- [ADR-0009](0009-windows-bat-launchers-as-entry-points.md)
- [ADR-0019](0019-single-quality-entrypoint.md)
- [ADR-0032](0032-verification-tooling-may-be-added-outside-phase-scope.md)

## Supersedes

None.

## Superseded By

None.
