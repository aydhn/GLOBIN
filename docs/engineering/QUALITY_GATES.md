# Quality Gates

Which checks must pass, where they run, and what happens when one fails.

GLOBIN develops on `master` with no pull request and no reviewer
([ADR-0005](../adr/0005-master-only-git-workflow.md)). Nothing stands between a
change and the repository except these gates, so they are the review. That is
why a gate here either fails the build or does not exist — a warning nobody has
to act on is a comment with extra machinery.

Test levels, fixture rules and the taxonomy are in
[`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md). Rule-by-rule reasoning for
Ruff and mypy is in [`STATIC_ANALYSIS.md`](STATIC_ANALYSIS.md). This document is
about the gates themselves.

---

## One definition, three places it runs

Every check is a named command in `tools/quality/commands.py`. The developer,
the pre-commit hook and CI all invoke that table rather than keeping their own
lists.

The reason is drift. When CI carries its own copy of the command list, a check
added in one place and not the other produces the worst kind of failure: a
build that breaks on something nobody can reproduce locally, or a check that
quietly stopped running months ago and nobody noticed because everything was
green.

```bash
python -m tools.quality full
```

| Command | Runs | Typical use |
|---|---|---|
| `fast` | Smoke tests, lint, format check | The inner edit loop |
| `full` | Lint, format, type check, coverage suite | Before staging, and in CI |
| `lint` | `ruff check` | Iterating on one failure |
| `format` | `ruff format --check` | Iterating on one failure |
| `typecheck` | `mypy` over package, suite and tooling | Iterating on one failure |
| `smoke` | The smoke level only | Fastest possible signal |
| `unit` | The unit level only | While writing a unit |
| `architecture` | Contract and architecture levels | The repository guards |
| `integration` | The integration level only | While wiring components together |
| `property` | The property level, exploratory Hypothesis profile | Searching for a new counter-example |
| `coverage` | Full suite with branch coverage and its floor | Before delivery |
| `shards` | The suite partitioned N ways, each shard its own process | Proving no test depends on sharing a process with another |
| `mutation` | Mutation testing of the declared targets, against the baseline | Proving the tests would notice a change |
| `evidence` | The suite, coverage, lint and typing in one run, recorded as JUnit XML, coverage in four forms, each tool's findings, a digested manifest and checksums | Producing something a machine can read and a person can check later |
| `fix` | `ruff check --fix` — **modifies the tree** | Applying safe fixes |
| `reformat` | `ruff format` — **modifies the tree** | Applying formatting |

Only `fix` and `reformat` write anything. Every other command reports and
changes nothing, because a gate that edits the code on its way past makes its
own result meaningless: the thing that passed is no longer the thing you have.

`scripts/verify.ps1` runs `full` and then inspects the branch and working tree.
It is still the command to run before staging:

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

---

## Failure semantics

A gate is either passed, failed, or not run. There is no fourth state, and
"not run" never reports as "passed".

- **The first failing step stops the command.** Later checks are not attempted,
  because their output would compete with the failure you need to read.
- **Exit codes are propagated, not summarised.** The caller gets the tool's own
  code. Collapsing everything to `1` discards the difference between a failing
  test and a tool that could not start.
- **A missing tool exits `127`.** Distinct from any code a check itself
  produces, so a log can never confuse "lint failed" with "lint never ran".
- **Nothing is installed automatically.** If a tool is absent the command says
  which one and stops. Installing it silently would make the result depend on
  the order things were run in.

The anti-patterns this rules out are worth naming, because each one leaves a
build green: appending `|| true` to a command, setting `continue-on-error` on a
CI step, downgrading a failure to a warning, skipping a test when its
precondition is missing, and treating an absent tool as nothing to check.
A contract test asserts the CI workflow contains none of them.

### The one deliberate exception: `evidence`

`evidence` runs every gate and *then* returns non-zero, rather than stopping at
the first failure. This is not a softer rule; it is the same rule applied to five
gates instead of one.

The reason is what the command is for. A run that stopped at `ruff` would produce
no test evidence at all — which is the one thing it exists to produce, and the
thing somebody wants most when something has just failed. Every gate's result is
recorded separately in the manifest's `gates` section, so "the suite failed" and
"the types failed" are never one undifferentiated failure, and the command's own
exit code still reports the worst of them.

Nothing else changes. Failure is never masked, "not run" still outranks "failed"
in the verdict, and `full` — the gate this repository actually blocks on — still
stops at its first failing step.

---

## Coverage

Branch coverage, measured over `globin` and `tools`, with a repository-wide
floor of **95 %**.

Branch rather than line, because a line-covered `if` whose false arm never runs
reads as tested and is not. For code made largely of conditionals, the line
percentage alone is close to meaningless.

**The floor is a regression detector, not a target.** It sits below the actual
figure on purpose, so that ordinary refactoring does not fail the build while a
module quietly losing its tests does. Raising the number by adding tests that
assert nothing would improve the metric and weaken the suite, which is the exact
trade this project refuses. Judge a suite by what it would catch.

Phase 005 tested that rule against its own temptation. It was a phase about test
quality, measured coverage stood at 99.57%, and raising the floor would have
looked like progress. The floor stayed at 95, because a phase that tightens a
threshold it happens to be comfortably above has learnt nothing about the
threshold — it has only recorded where the code was that week. What the phase did
instead was read the partial-branch column and test the decisions it named: the
`find_spec` failure arm in `tools/quality/runner.py`, the paths the error
taxonomy added, and a defect in `import_cycles` that no coverage number would
ever have shown, because the affected line was executed on every run.

Three lines are knowingly uncovered, and they are the same line three times: the
`if __name__ == "__main__"` guard in `tools/quality/__main__.py`, in
`tools/quality/mutation/__main__.py` and in `tools/quality/execution/__main__.py`.
Each runs on every real invocation and in another process, so the suite cannot
see it. All three are exercised by a test that starts the module rather than
annotated with a `pragma`, because a pragma would claim coverage this repository
does not have.

Excluded from measurement, via `exclude_also` so that coverage's own defaults
are kept rather than replaced:

| Excluded | Why |
|---|---|
| `if TYPE_CHECKING:` bodies | Never execute at runtime, by construction |
| A bare `...` body | The whole declaration of a `Protocol` method; nothing to test |
| `@abstractmethod` bodies | Same reason |

Coverage artefacts (`.coverage`, `coverage.xml`, `htmlcov/`) are ignored by
Git and must never be committed.

A later phase may impose a higher floor on a specific area — risk and execution
code are the obvious candidates — without changing this repository-wide one.

---

## The pre-commit gate

Fast local feedback, installed once:

```bash
python -m pre_commit install
```

Run it over everything without committing:

```bash
python -m pre_commit run --all-files
```

It runs file hygiene, secret detection, Ruff lint and format checks, and the
contract and architecture levels of the suite. It deliberately does **not** run
the full suite, type checking or coverage: those belong to `verify.ps1` and CI,
where waiting is acceptable.

**Four hooks rewrite files** rather than only reporting: `trailing-whitespace`,
`end-of-file-fixer`, `fix-byte-order-marker` and `ruff-format`. When one of them
changes something, pre-commit aborts the commit and leaves the change unstaged.
It never commits on your behalf — read the diff, stage it, commit again.

`ruff-check` runs **without** `--fix`, so a lint failure is understood rather
than silently rewritten.

`ruff-pre-commit` is pinned to the same Ruff version the quality gate and CI
use. Two versions of a linter means two verdicts, and a file that passes locally
while failing in CI with nothing changed in between. A contract test asserts the
two pins agree.

---

## Continuous integration

`.github/workflows/quality.yml` runs on pushes to `master` and on pull requests
targeting it. It exists to verify, never to repair, and it runs under the
principle of least privilege: the token it is handed can read the repository and
do nothing else.

| Property | Setting | Why |
|---|---|---|
| Token permissions | `contents: read` | The jobs read the repository and write nothing back |
| Action references | Full 40-character commit SHAs | A tag is mutable; its owner can change what runs here |
| Secrets | None | Quality checks need no credential, and GLOBIN has none |
| Network | Package index only | No exchange, no market data, no external API under test |
| Runner | `windows-latest` | The only platform GLOBIN declares, and the one that exercises the CRLF rules |
| Interpreters | 3.12 and 3.14 | The floor `requires-python` declares, and the version development happens on |

Nothing in the workflow commits, pushes, formats or applies a fix. The GLOBIN
package itself is not installed: the suite runs from `src/` via `pythonpath`,
and building a distribution is work that belongs to Phases 017-032 and must not
be described as verified before then.

Property tests run under the reproducible Hypothesis profile, and so does the
local gate. Selecting it in the command table rather than from an environment
variable is what keeps CI and a developer's machine examining the same inputs; a
machine with the variable unset would otherwise run a quietly different gate.

The interpreter matrix is **provisional**. Interpreter selection and pinning is
Phase 018; dependency resolution and locking is Phase 020. Until those phases
run, the versions pinned in the workflow are a reproducibility measure, not a
supported-platform claim.

---

## Deliberately deferred

Recorded here so that their absence is a decision rather than an oversight.

| Deferred | Owning phase |
|---|---|
| Virtual environment lifecycle | 019 |
| Dependency resolution and lockfiles | 020 |
| Interpreter selection and pinning | 018 |
| Packaging build verification | 017-032 |
| Docstring linting and naming conventions | 013 |
| Secret storage and credential handling | 028-029 |
| Concurrent workers, dynamic load balancing and worker-scoped fixtures — everything `pytest-xdist` would provide | 014, which owns dependency review |

Phase 004 configures the quality tools it uses and pins the versions it runs
against. It does not solve dependency management, and nothing here should be
read as having done so.

---

## Related documents

| Question | Document |
|---|---|
| What are the test levels? | [`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) |
| Why these lint and type rules? | [`STATIC_ANALYSIS.md`](STATIC_ANALYSIS.md) |
| When is a change finished? | [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) |
| What must all code satisfy? | [`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md) |
| Why was a tool chosen? | [ADR-0018](../adr/0018-quality-toolchain-and-explicit-strictness.md) |
