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
| `aggregate` | This run's job results and its published evidence, reduced to one verdict | Deciding whether a whole CI run passed, and saying why |
| `supply` | Dependency inventory, a CycloneDX 1.7 SBOM, a `pip-audit` vulnerability audit, waiver expiry, action pinning, content secret hygiene, and what the platform will and will not do | Establishing what this repository depends on and what that costs |
| `governance` | Code ownership, the security policy's required sections, sensitive-path coverage, the reporting channel, and that no public issue template collects vulnerability detail | Establishing that the governance arrangement still describes this repository |
| `release` | The foundation acceptance matrix, the version, the tag it implies, the changelog, the release documents and the notes configuration. `release ready` adds the preconditions — branch, clean worktree, agreement with the remote | Establishing that a release may be cut, and publishing the evidence it will carry |
| `runtime` | The Windows host and its kernel version, the interpreter's implementation, minor line, patch floor, architecture, width and build, the project environment's provenance and settings, and where `pip` would install from. `runtime bootstrap` adds building the environment | Establishing which machine and which interpreter the other gates were measured on |
| `wheels` | The wheel survey in [`wheel-survey.toml`](wheel-survey.toml) against the runtime contract, with every recorded verdict recomputed from the wheel filenames recorded beside it. `wheels probe` adds asking the index whether the record is still true | Establishing that the libraries the roadmap schedules can be installed on the pinned interpreter |
| `drift` | This host against the baseline accepted in `.globin/drift/`, classified by [`drift-policy.toml`](drift-policy.toml), with every recorded repair verdict recomputed from the action declared beside it. `drift accept` records a baseline; `drift repair` performs the repairs marked in-place | Establishing that the machine is still the machine the other gates were measured on, and what to do when it is not |
| `lock` | `pylock.dev.toml` against [`lock-policy.toml`](lock-policy.toml) and [`runtime-contract.toml`](runtime-contract.toml), with every hash, artefact host, wheel tag and cross-register version recomputed from the lock's own evidence. `lock installed` adds this environment; `lock relock` and `lock upgrade` regenerate the lock and reach the index | Establishing that what the repository declares, what CI pins and what is installed are one resolution rather than three |
| `materialize` | Whether the environment `pylock.toml` describes could be installed from the local wheelhouse with **no network**. Artefact selection is `packaging.pylock`'s -- the specification's own reference implementation -- handed tags built from the **declared** target rather than from this interpreter, so the verdict is the same on every runner. Every cached artefact is re-hashed against the digest the lock records, and a file that hashes to something else is **left in place and reported** rather than deleted or re-fetched. With an empty wheelhouse the verdict is `unmeasured` and the exit code 3, exactly as `drift` behaves with no baseline: artefacts are hundreds of megabytes and are not committed, so a fresh clone has established nothing rather than established an absence | Establishing that the locked environment is reproducible from bytes already on this machine, and that no path silently reaches an index to make that true |
| `stack` | The installed numerical and dataframe stack against [`stack-contract.toml`](stack-contract.toml): the four places a version is written down held against each other, each artefact's own record of the wheel it was built from, and seven behaviour probes run against the real libraries | Establishing that the thing inside the wheel *computes* what [`../PRECISION_POLICY.md`](../PRECISION_POLICY.md) and [`../TIME_POLICY.md`](../TIME_POLICY.md) assume, which no filename can settle — see [`SCIENTIFIC_STACK.md`](SCIENTIFIC_STACK.md) |
| `gpu` | This host against [`gpu-contract.toml`](gpu-contract.toml): the declared target against the runtime contract, and a recorded state for every capability the contract names — device presence, driver version, compute capability, CUDA runtime and CUDA toolkit — read only through the documented `nvidia-smi` fields the contract permits | Establishing what this machine actually has, so that no later phase assumes it. **Absence is a state, not a failure**: a host with no NVIDIA device exits `0` — see [`GPU_CAPABILITY.md`](GPU_CAPABILITY.md) |
| `benchmark` | The workloads [`benchmark-contract.toml`](benchmark-contract.toml) declares, measured on this host with the declared warmup, repeat count and reduction, and every verdict recomputed from the recorded nanoseconds against the declared speedup threshold | Establishing which workloads actually benefit from GPU execution here. **An unadopted backend is a state, not a failure**: every CUDA workload records `unavailable` naming the phase that would change that — see [`GPU_BENEFIT.md`](GPU_BENEFIT.md) |
| `endpoint` | The diagnostics surface against [`endpoint-contract.toml`](endpoint-contract.toml): the route table, the loopback addresses, every bound and default, every route's switch, both content types, each attribute vocabulary, and the cardinality arithmetic behind all five metric budgets — each recovered from `src/globin` rather than believed. Also two absences the value type cannot see: that the module which binds spells **no address at all**, loopback included, and that no wildcard appears anywhere in the package | Establishing that what the surface promises is what it implements. **It binds nothing and reaches nothing**, so it runs identically where the surface has never been enabled — see [`DIAGNOSTICS_ENDPOINT.md`](DIAGNOSTICS_ENDPOINT.md) |
| `venue` | The Binance API reality registry against [`binance-api-reality.toml`](binance-api-reality.toml): every capability row's provenance, the six status words, that **nothing claims to have been observed**, every identity's uniqueness, one current schema per family, every endpoint's scheme, that a FIX endpoint requires TLS **and** SNI, and that no endpoint's host contradicts the environment it is filed under. Parsed by a reader that imports none of `globin`, so a registry the package would mis-read is caught by code it does not share | Establishing that what the registry claims about the venue is internally consistent and attributable. **The default reaches nothing**; `refresh` reaches the official machine-readable sources and is a separate word — see [`BINANCE_API_REALITY.md`](BINANCE_API_REALITY.md) |
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

**`fail_under = 95` does not mean 95 on its own.** Two different comparisons act
on it, and they are not the same comparison. The line a person reads is printed
with a plain `total < fail_under`, so 94.86 % renders as *"FAIL Required test
coverage of 95.0% not reached"*. The exit code comes from coverage.py's
`should_fail_under`, whose last line is `round(total, precision) < fail_under` —
and at the default `precision` of 0, `round(94.86, 0)` is 95, so the process
exits 0. The real floor was **94.5 %**, and between there and 95 % a run printed
FAIL and reported success.

Phase 035 met it: CI's 3.14 leg measured 94.88 %, printed the failure, and the
job passed. The shortfall surfaced two commits later in the `evidence` job, which
applies the threshold to `coverage.json`'s `totals.percent_covered` itself rather
than trusting the exit code. `precision = 2` in `[tool.coverage.report]` is what
closes the gap — two decimals, because that is what the message already prints,
so the number a person reads and the number the exit code is computed from are the
same number. `tests/contract/test_quality_contract.py` compares the two
comparisons across the boundary and fails if they can ever disagree again.

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

`.github/workflows/quality.yml` runs on pushes to `master`, on pull requests
targeting it, and on merge-group entries. It exists to verify, never to repair,
and it runs under the principle of least privilege: the token it is handed can
read the repository and do nothing else.

The table below is the summary. What CI is trusted with, why each setting is what
it is, and the procedure for changing a pin belong to
[`CI_SECURITY.md`](CI_SECURITY.md).

| Property | Setting | Why |
|---|---|---|
| Token permissions | `contents: read` | The jobs read the repository and write nothing back |
| Action references | Full 40-character commit SHAs | A tag is mutable; its owner can change what runs here |
| Secrets | None | Quality checks need no credential, and GLOBIN has none |
| Network | Package index only | No exchange, no market data, no external API under test |
| Runner | `windows-latest` | The only platform GLOBIN declares, and the one that exercises the CRLF rules |
| Job timeouts | Declared per job, derived from measured runs | Undeclared is not unbounded; it is GitHub's six-hour ceiling |
| Cancellation | Superseded runs, except on `master` | A cancelled master run leaves that commit with no evidence |
| Interpreters | 3.12 and 3.14 | The floor `requires-python` declares, and the version development happens on |

Nothing in the workflow commits, pushes, formats or applies a fix. The GLOBIN
package itself is not installed: the suite runs from `src/` via `pythonpath`,
and building a distribution is work that belongs to Phases 017-032 and must not
be described as verified before then.

Property tests run under the reproducible Hypothesis profile, and so does the
local gate. Selecting it in the command table rather than from an environment
variable is what keeps CI and a developer's machine examining the same inputs; a
machine with the variable unset would otherwise run a quietly different gate.

The interpreter matrix is **still provisional, for one remaining reason.** Phase
017 pinned the interpreter — [`runtime-contract.toml`](runtime-contract.toml)
names CPython 3.14 exactly — and Phase 018 verified that the libraries the roadmap
schedules publish wheels for it ([`WHEEL_AVAILABILITY.md`](WHEEL_AVAILABILITY.md)).
Phase 020 then locked the toolchain ([`DEPENDENCY_LOCKING.md`](DEPENDENCY_LOCKING.md)),
and a pip-produced lock is valid for one interpreter and one platform. So the
second matrix entry remains a compatibility check rather than a second supported
runtime: it cannot install from the lock, and the versions the workflow pins for
it are still a reproducibility measure rather than a supported-platform claim.

### The aggregate gate, and which check to require

The workflow presents several status checks. Exactly one of them is meant to be
required on `master`:

> **`Quality gate`**

It is the `aggregate` job, and it succeeds only when every job in
`[tool.globin.workflow] required_jobs` reported success **and** the evidence that
run published says every gate passed. A contract test compares that list against
the jobs actually declared in the workflow, in both directions, so a job added
without being considered — or removed while still required — fails the suite
rather than quietly changing what the check means.

**Why not require the other checks instead.** Two of them are named
`Quality (Python 3.12)` and `Quality (Python 3.14)`, because a matrix job's check
name carries its matrix value. A rule naming those breaks the day an interpreter
is added or removed. Phase 020 did not do that -- the lock serves the pinned line
only, and the matrix kept both entries. `Quality gate` carries no operating system, no
version and no matrix value, so it survives.

**Why the check view alone is not enough.** GitHub skips a job whose dependency
failed, and a skipped required check is not reported to branch protection as a
failing one. A rule that trusted the check view could therefore be satisfied by a
run in which everything it depended on had failed. The aggregate closes that by
running when something upstream did not — `if: ${{ !cancelled() }}` — and by
requiring each job to have *reported* success rather than merely to have not
reported failure. Anything it cannot determine exits `3`, which is not a pass.

**Branch protection is not configured here.** It is a repository setting, in a
different control plane from this repository's contents: no file in this tree can
turn a check into a required one, and nothing in this phase attempts to. Making
`Quality gate` required is a one-time action in the repository's settings, and
until somebody takes it the check is informative rather than blocking. Saying so
plainly is the point — a document claiming the rule exists would be describing a
guarantee the code cannot give.

### Evidence artifacts and their integrity

| Artifact | Contents | Retention |
|---|---|---|
| `test-evidence-windows-py314` | The nine evidence files and the browsable coverage tree | 30 days |
| `quality-gate-verdict` | `aggregate-quality.json` — the verdict and its reasons | 30 days |
| `supply-chain-evidence` | `supply-manifest.json`, the CycloneDX SBOM and the dependency inventory | 30 days |
| `governance-evidence` | `governance-manifest.json` — the ownership arrangement and what it was checked against | 30 days |

**Each artifact uploads exactly one directory, and that is load-bearing rather
than tidy.** `upload-artifact` roots an archive at the *least common ancestor* of
its paths, so adding a second path silently moves every file down a level.
Phase 015 did exactly that to `supply-chain-evidence` and broke the `attest`
job, whose `subject-path` then matched nothing. A new artefact gets a new
artifact, not another line in an existing one.

Thirty days is long enough to diagnose a failure somebody noticed late, short
enough not to accumulate, and unchanged since Phase 010. GitHub permits 1 to 90,
and a repository or organisation setting can cap it lower than the value declared
here — `retention-days` is a request rather than a guarantee.

**Two integrity layers, and neither contains the other.**

`checksums.sha256` covers every file *inside* the evidence bundle and is written
before the upload. The bundle's own SHA-256 is computed *by GitHub* as the upload
completes, so nothing inside it can carry that value — an artifact holding its own
digest would be a file containing its own hash. It is published as a job output
instead, recorded in `aggregate-quality.json`, and shown in the step summary.
[ADR-0042](../adr/0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md)
records the split.

The aggregate job re-verifies the bundle after downloading it, using the same
`python -m tools.quality.evidence verify` the evidence job ran. The bytes are
different — they have been through an upload and a download — so a bundle
corrupted in transit is caught rather than trusted.

### When the gate fails

The step summary names the failing job or gate and carries the commands to
reproduce it. In order of what they cost:

| Question | Command |
|---|---|
| Does the tree pass at all? | `python -m tools.quality full` |
| What did the last local run measure? | `python -m tools.quality evidence` |
| Is the evidence intact? | `python -m tools.quality.evidence verify` |
| What is the verdict, and why? | `python -m tools.quality aggregate` |

Run locally, `aggregate` reads whatever evidence the last `evidence` run wrote,
because there is no workflow context on a developer's machine. It is the same
evaluator CI uses, so a verdict here and a verdict there mean the same thing.

A gate reporting `not run` is not a milder version of a failure. It means the run
could not establish the answer, which casts doubt on the gates that did report —
so the aggregate treats it as outranking a plain failure, the rule
`tools/quality/execution/plan.py` already applies to a shard.

---

## Deliberately deferred

Recorded here so that their absence is a decision rather than an oversight.

**The table is empty.** Phase 032 closed the last row it held, and an empty table
is left standing rather than deleted so that the next deferral has somewhere
obvious to go.

Six rows have left this table when the phases owning them delivered. Docstring
linting and naming conventions were Phase 013's and are now part of the `D` rules
in `pyproject.toml`; the `pytest-xdist` question was Phase 014's and was answered
by `shards`, which partitions the suite by a stable digest rather than by a plugin
([ADR-0036](../adr/0036-test-execution-is-sharded-by-a-stable-digest-not-by-a-plugin.md)).
*Interpreter selection and pinning* and *virtual environment lifecycle* were both
delivered by Phase 017 under the fourth scope amendment
([ADR-0051](../adr/0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md)),
and this table went on naming them against phases 018 and 019 until Phase 018
noticed and corrected it. *Environment drift detection and repair* was Phase 019's
and is now the `drift` gate above
([ADR-0053](../adr/0053-drift-is-measured-against-an-accepted-baseline-and-repair-is-a-classification.md)).
*Packaging build verification* was recorded against phases 017-032 and was met by
Phase 032, the last of them, by building and installing the artefacts rather than
by reasoning about them. `build` 1.5.0 with the Hatchling backend produced
`globin-0.1.0-py3-none-any.whl` — 101 members, holding `globin/` and its
`.dist-info` and nothing else — and `globin-0.1.0.tar.gz`, 654 members, the whole
tree. Installed into a throwaway environment, `globin --version` answered `0.1.0`
and `globin bootstrap check` refused at `python.environment`: the fail-closed
refusal Phase 021 designed, reached from an installed artefact rather than from
the source tree.
A deferral that has been met is removed rather than left to read as outstanding —
including when what met it was a phase other than the one recorded here.

**Building is verified, and is deliberately not a gate.** `python -m build` cannot
run offline here: `hatchling` is the build backend and is not in `pylock.dev.toml`,
so build isolation fetches it from an index. Every command in the table above runs
on an aeroplane, and adding one that does not would make that sentence false. Making
it recurring means locking the backend, which is a dependency review under
[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) rather than a line of tooling.

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
