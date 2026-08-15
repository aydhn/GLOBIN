# ADR-0052 — Wheel availability is a recorded survey whose verdict is recomputed, and a gap is owned rather than fixed

## Status

Accepted — Phase 018.

## Context

Phase 017 pinned CPython 3.14 and built `.venv` from it. It did so **before**
anything verified that the libraries this programme schedules publish wheels for
that line, which is the order `ROADMAP.md` stated, reversed.
[ADR-0051](0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md)
recorded the inversion rather than arguing it away, and stated the consequence
plainly: *"if the survey finds the planned stack cannot run on the pinned line,
the contract this phase wrote is what changes."*

[ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md)
left two refusals explicitly provisional on the same survey — free-threaded builds
and prereleases — saying of the first that *"Phase 018 has not yet surveyed
whether the planned stack publishes for it"*. Both are decisions the repository
holds today on the strength of nobody having looked.

So Phase 018 has a question, and it needed a shape. Four pressures decided it.

**A question asked once decays.** Nineteen distributions were read on one day.
Upstream projects cut releases, withdraw wheels, and change `Requires-Python`. A
survey recorded and never re-examined is a document that was true, which reads
exactly like one that is.

**A generated answer checks nothing.** Every machine-readable contract here —
`action-pins.toml`, `dependency-reviews.toml`, `mutation-baseline.toml`,
`governance.toml`, `foundation-acceptance.toml`, `runtime-contract.toml` — carries
the same banner, and the same argument: a file generated from the thing it
describes could only ever agree with it.

**A hand-written answer is unfalsifiable.** This is where a survey differs from a
pin manifest. `action-pins.toml` records a commit SHA, and the workflow either
uses that SHA or does not. A survey records a *judgement about evidence*, and a
file holding only `verdict = "available"` cannot be argued with by anything.

**Substring matching gets this wrong, and would have.** `xgboost` and `lightgbm`
publish `py3-none-win_amd64` — platform-specific, interpreter-agnostic, native
code behind `ctypes`. A survey grepping for `cp314` reports a gap in both that
does not exist, and would have sent this phase to reopen an interpreter contract
over nothing. The reverse error is worse: `cp314-cp314-win_amd64` looks like it
serves a free-threaded `3.14t` interpreter and does not.

## Decision

### 1. The survey is a declaration, and nothing writes it

`docs/engineering/wheel-survey.toml` is written by a person who read each
project's published metadata. One `[[library]]` per distribution the roadmap — or
the Phase 001 source ledger it rests on — names, carrying the phase that schedules
it, the version surveyed, the published `Requires-Python`, the wheel filenames
observed, a verdict, the canonical source and a reason.

### 2. The evidence is recorded, so the verdict can be recomputed

This is the decision that separates this record from `action-pins.toml`'s.

Because the **filenames** are in the file, `python -m tools.quality wheels` parses
their PEP 425 tags offline and decides for itself whether any of them serves the
pinned interpreter. An entry claiming availability whose own evidence does not
support it fails without asking the index anything.

The verdict vocabulary is three words — `available`, `source-only`, `absent` — and
only the first is decidable offline. Distinguishing the other two means asking
whether a source distribution exists, which is the probe's question.

### 3. Tags are parsed, and the pairing decides

Compatibility is decided by the interpreter tag **paired with** the ABI tag, never
by either alone and never by substring. `none` binds to no ABI and frees the
interpreter tag to be any version at or below the target's; `abi3` does the same
but is never a route onto a free-threaded build, which does not offer the limited
API; an exact `cp3NN` ABI pins the interpreter tag to match and never substitutes
across the free-threaded boundary in either direction.

The matcher is a **deliberate subset** of PEP 425 — one implementation, one minor
line, one platform, no manylinux or macOS version ranges, no ranking of
candidates. It answers *does a wheel exist that the pinned interpreter could
install*, and the docstring says so rather than implying more.

### 4. Version specifiers are decided or refused, never guessed

Only `>=`, `>`, `<=` and `<` are supported. `==`, `!=`, `~=`, `===`, wildcards,
and any bound carrying a patch component inside the pinned minor line are refused
**by name**, because a minor line alone cannot decide `<3.14.3`. An empty
`Requires-Python` is refused too: a distribution that publishes none has made no
claim, and silence is not permission.

This is the same narrowing `tools/quality/supply/inventory.py` already applies to
its `>=`-only comparison, for the same reason — full PEP 440 is a `packaging`
dependency, and it is not needed to answer this question.

### 5. The offline gate and the network probe are separate commands

`python -m tools.quality wheels` reaches nothing. `python -m tools.quality.wheels
probe` asks the index whether the record is still true.

The split is `tools/quality/supply`'s, for its reason: `full` runs before every
commit and must work on an aeroplane. The probe runs in the `supply`
continuous-integration job, which is already the only job that reaches outside the
runner, so the network dependency is declared in one place rather than two. An
index that cannot be read reports unmeasured and exits 3, which is never a pass.

### 6. A gap is recorded and owned; it is not a failure

The roadmap asks this phase to *record each gap rather than assuming one*. A
library whose upstream publishes no wheel is a fact about the world, and a gate
red until somebody else's release schedule changes is a gate people learn to
ignore.

So a verdict may say there is no wheel, and the entry must then carry
`resolved_by` naming a phase that exists and has not shipped. What fails is an
**unowned** gap. This is `vulnerability-waivers.toml`'s bargain: the thing demanded
is not the absence of a problem but a name against it.

### 7. The free-threaded verdict is computed, reported, and never fails the gate

The same evidence answers a second question ADR-0050 left open, by matching each
recorded filename against the free-threaded twin of the declared target. The gate
names the libraries that would block the change and **passes**.

A gap there is ADR-0050's refusal being correct, not something going wrong.
Failing on it would make the gate red for holding the position the project
deliberately holds. Naming the blockers is what makes the refusal revisitable
rather than permanent.

### 8. This phase does not resolve, lock, or adopt anything

No resolver runs. No lock file is written. `pyproject.toml` is unchanged and
`project.dependencies` is still empty. Nothing surveyed here has been through the
six-question review in `docs/DEPENDENCY_POLICY.md`, and appearing in the survey is
not a step towards adoption — it is a claim that the roadmap schedules the
library, checked against the roadmap.

### 9. No dependency was added to build this

The index is read with `urllib.request`; the tags are parsed with `re`. The
alternative was `packaging`, which implements PEP 425 and PEP 440 properly and is
already present transitively behind `pip-audit` — but is not declared, and
declaring it would mean a fourth register entry, a written review, and a runtime
dependency on a library whose full generality this gate does not use.

The owner authorised adding one with a written record if needed. None was needed,
and recording that as a decision rather than an omission is the point of this
paragraph.

## Consequences

**Good.** The interpreter contract is no longer held on the strength of nobody
having looked. Every scheduled library has a wheel for CPython 3.14 on
`win_amd64`, so `runtime-contract.toml` is unchanged — and the survey that
establishes it can be re-run rather than re-argued. Two of ADR-0050's provisional
positions now rest on evidence: the free-threaded refusal has exactly one named
blocker, and the choice of an exact minor line rather than a floor is
independently supported by the Binance SDK family's uniform `<3.15` cap, which is
the one dependency the system cannot do without.

**Costs, accepted.** A file that has to be edited by hand when an upstream project
cuts a release, and a probe that will report drift for changes nobody here caused.
That noise is the mechanism working — a record nobody is forced to revisit is a
record that quietly stops being true — but it is noise, and it will arrive on days
that have nothing to do with GLOBIN. The survey is also a *point in time*: it
says a wheel was published, not that it installs, not that it works, and not that
its dependencies resolve. Phases 020-025 answer those, and this record does not.

**What this does not decide.** Which libraries GLOBIN adopts, in what version,
under whose review. Dependency resolution and locking. Whether a wheel that exists
also functions on this host. Whether the prerelease refusal in ADR-0050 still
holds — the survey read final releases only, and that is recorded as unexamined
rather than counted as confirmed.

## Alternatives Considered

**Generate the survey from the index on every run.** No hand-written file, no
drift, no maintenance. Rejected on the argument every manifest here already makes:
a generated file agrees with its source by construction, so it can report nothing.
It would also put the network in the middle of a gate that must run offline, and
make the answer depend on PyPI being up.

**Record only the verdict, as `action-pins.toml` records only a SHA.** Simpler,
and consistent with the closest precedent. Rejected because the analogy breaks: a
pin is a fact that can be compared against the workflow, while a verdict is a
judgement that nothing offline could check. Recording the filenames is what turns
an assertion into evidence.

**Use `packaging` for tag and specifier handling.** Correct, complete, and
maintained by PyPA. Rejected under question 5 of `docs/DEPENDENCY_POLICY.md`, on
the precedent of ADR-0033's mutation harness, ADR-0036's shard planner and Phase
014's SBOM generator: the subset needed here is small, exactly specified, and
refuses what it cannot decide, which a general library cannot do on this
repository's behalf. The cost is that the subset must be maintained and its limits
stated — which decision 3 does.

**Attempt an install into a throwaway environment instead of reading tags.**
Unambiguous, and it would answer the stronger question of whether the library
works. Rejected as a different phase's work: it needs a network, minutes rather
than milliseconds, gigabytes of downloads for the machine-learning stack, and it
would answer for one host rather than for the contract. Phases 022-025 exist to
make exactly those measurements.

**Fail the gate on any gap, including the free-threaded one.** Simpler rule, no
`resolved_by` field, no third verdict word. Rejected because it makes the gate's
verdict depend on other people's release schedules, and because it would fail on
the free-threaded gap — which is the repository's own deliberate position, not a
defect.

**Do nothing, and treat Phase 018 as the formality ADR-0051 warned it might look
like.** The interpreter is already pinned; the survey arrives after the decision
it was meant to inform. Rejected because ADR-0051 answered it in advance: the
survey is what could change the contract, and finding that it does not is a result
only available to somebody who looked.

## Risks and Trade-offs

**The record rots and the probe is the only thing that notices.** Its
characteristic failure is a run on a day PyPI is slow or down, reporting
unmeasured and being read as flaky rather than as unmeasured. The observable
signal is `WHEELS_INDEX_UNREACHABLE` appearing in consecutive manifests; the wrong
response is `continue-on-error`, which `docs/DEPENDENCY_POLICY.md` prohibits by
name.

**The tag subset is wrong in a case nobody has met.** Confidence here is
moderate, not high: the matcher is checked against nineteen real distributions and
a property suite, which is a good sample and not a proof. The failure mode is
quiet — a wheel reported available that an installer would refuse — and the signal
is Phase 022 failing to install something this survey called available. That is
late, and it is the honest position.

**The survey set is the author's reading of the roadmap.** Most entries are named
in the Phase 001 ledger; `numpy` and `pandas` are a judgement about what Phase 022
means by "the numerical and dataframe stack". A library the programme genuinely
needs and nobody listed will not be missed by any check here, because nothing can
compare a survey against an intention. The mitigation is that omissions are
*stated* — the document names what is deliberately absent and why — so a reader
can disagree with a decision rather than discover a silence.

**`resolved_by` becomes a place to park things.** A gap owned by a phase 200
numbers away is technically owned and practically forgotten. Nothing here bounds
how far ahead an owner may be, and the signal is a survey accumulating entries
whose `resolved_by` never arrives.

**The free-threaded finding is read as a plan.** Naming one blocker invites
somebody to conclude that removing it settles the question. It does not: the
survey says wheels exist, and whether a free-threaded interpreter is *right* for
this system is an argument ADR-0050 made on other grounds too.

## References

- [ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md) — the pin, and the two refusals this survey answers
- [ADR-0051](0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) — why this phase exists, and what it is permitted to change
- [ADR-0044](0044-dependency-review-is-a-written-process-with-a-generated-inventory.md) — the register-against-tree pattern this follows
- [ADR-0033](0033-mutation-testing-is-a-repository-native-ast-harness.md) — the precedent for writing rather than depending
- [ADR-0024](0024-tests-are-offline-and-isolated-by-construction.md) — why the fetcher is injected
- `docs/engineering/WHEEL_AVAILABILITY.md` — what the survey found, and how to add to it
- `docs/DEPENDENCY_POLICY.md` — how a surveyed library becomes a declared one
- `docs/research/phase_018_sources.md` — every distribution read, and when

## Supersedes

Nothing.

## Superseded By

Nothing yet.
