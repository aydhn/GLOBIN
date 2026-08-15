# ADR-0051 — Phase 017 absorbs interpreter pinning and the environment lifecycle, and this is not covered by precedent

## Status

Accepted — Phase 017.

## Context

`ROADMAP.md` divided the opening of the second band into three phases:

| Phase | Title |
|:-----:|---|
| 017 | Windows Host Requirements Survey |
| 018 | Python Interpreter Selection and Pinning |
| 019 | Virtual Environment Lifecycle Management |

`docs/release/FOUNDATION_ACCEPTANCE.md` says the same thing in its Phase 017
handoff table, which assigns "Python interpreter selection and pinning, verified
against wheel availability" to Phase 018 and "Virtual environment lifecycle:
creation, validation, repair, recreation" to Phase 019. Two committed artefacts,
written at different times, agree.

The brief for this phase asked for all three at once: a host baseline, a CPython
version contract, install-manager discovery, and a deterministic `.venv`
bootstrap with recreation.

[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) anticipated
this. It was the third amendment in five phases, it answered
[ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md)'s warning that a
third would be the signal the roadmap was being treated as a backlog, and it
closed by naming four conditions that a later amendment must satisfy to be
covered by its precedent:

> *nothing displaced, nothing deferred, no phase owns the work, and the two
> halves need each other*. An amendment that cannot say all four things is not
> covered by this precedent.

**This amendment cannot say all four.** It fails two of them, and the failures are
not marginal:

- **Nothing displaced** — false. Phases 018 and 019 are emptied of the work they
  were created to do, and both are retitled.
- **No phase owns the work** — false, and this is the sharper failure. Both
  phases own their half *by name*, in the roadmap and in the acceptance document.

Of the other two: nothing is deferred (the work moves earlier, not later), and
the halves are genuinely coupled — an interpreter cannot be pinned without
something to pin it for, and an environment cannot be created without a decision
about which interpreter creates it.

The owner was shown this analysis, including the two failing conditions and the
option of implementing Phase 017 alone, and chose the merged scope.

## Decision

### 1. Phase 017 is retitled and delivers all three

*Windows Host and CPython Runtime Baseline*. It delivers the host contract the
roadmap already assigned it, **and** the interpreter contract Phase 018 held,
**and** the environment lifecycle Phase 019 held.

### 2. Phase 018 and Phase 019 are retitled, not emptied

Band ranges, phase numbers and the sixteen-phase band width are unchanged, as they
were by all three earlier amendments. Both phases keep real work, and in each case
it is work this phase deliberately did not do:

| Phase | New title | Why it is real work |
|:-----:|---|---|
| 018 | Wheel Availability Survey for the Planned Stack | The roadmap made wheel availability a *precondition* of pinning — "after verifying wheel availability for the full planned stack". Phase 017 pinned without it. The survey is still owed, and it is what could yet reopen the free-threaded and prerelease decisions in [ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md). |
| 019 | Environment Drift Detection and Repair | Phase 017 delivers create, validate and recreate. It does not deliver *repair* — bringing a diverged environment back into compliance short of destroying it — nor detection of drift that appears over time as packages, the contract or the base interpreter change underneath it. |

### 3. The inversion Phase 018 now carries is recorded rather than glossed

Phase 017 pinned an interpreter before anything verified that the planned stack
has wheels for it. That is the roadmap's stated order, reversed.

The consequence is stated plainly here so that Phase 018 is not read as a
formality: **if the survey finds the planned stack cannot run on the pinned line,
the contract this phase wrote is what changes.** It is a floor in a file with a
test, not a decision anybody has to defend.

### 4. This does not licence further resequencing, and the precedent is now weaker

The four conditions still stand as the test. This record does not amend them,
widen them, replace them, or add a fifth — they are not superseded by anything
here. It records an amendment that failed the test and was made anyway, on the
owner's decision, with the failure written down.

A fifth amendment has a higher bar than a fourth did, not a lower one. The visible
cost of the programme's fixity is now four entries in five bands.

## Consequences

**Good.** The environment exists sixteen phases earlier than the roadmap
scheduled, so every phase from 018 onwards is developed under a known interpreter
rather than under whichever one `PATH` resolved. That is the same shape of benefit
ADR-0021 claimed for the testing foundation, and it is the honest argument for
this amendment.

**Costs, accepted.** `ROADMAP.md` carries a fourth entry in its *Scope amendments*
block. Two phases are retitled, which means anybody who read the roadmap before
this commit holds a stale picture of the band. `FOUNDATION_ACCEPTANCE.md`'s
handoff table, which is a Phase 016 artefact describing a released baseline, is
corrected in place rather than left describing a plan that no longer holds — the
`v0.1.0` tag is untouched and remains what it always was.

**What this does not decide.** Nothing about phases 020-032. The band still holds
sixteen phases and every slot is still occupied.

## Alternatives Considered

**Implement Phase 017 alone: the host survey and a read-only preflight.**
Governance cost zero — no amendment, no ADR, no retitling, and the roadmap's own
order preserved. Presented to the owner as the first option and rejected. It would
have left the repository running its gates under an unnamed interpreter for two
more phases, and left `pip install` in this directory writing to a user-site
directory shared with every other project on the machine.

**Implement 017 and 018, leaving the environment to 019.** A smaller amendment
displacing one phase rather than two. Presented and rejected. It is also the least
coherent of the three: pinning an interpreter and then not building anything from
it produces a contract nothing exercises, which is the state ADR-0021 argued
against when it declined to ship a testing foundation with nothing to apply it to.

**Renumber the band so nothing is displaced.** Rejected without being offered.
`ROADMAP.md`'s first rule is that the twenty band ranges never change, and
`src/globin/roadmap.py` encodes them with a contract test holding a second copy.
Renumbering would be a far larger change than the one being made, to avoid an
entry in a list whose whole purpose is to make this cost visible.

**Leave 018 and 019 with their original titles and mark them complete.** Rejected
as dishonest. Neither the wheel-availability survey nor environment repair has
been done, and marking a phase complete for work nobody performed would corrupt
the one signal `LAST_COMPLETED_PHASE` exists to carry.

## Risks and Trade-offs

**The precedent is read as permission.** ADR-0021 said an amendment that cannot
say all four things is not covered; this one cannot, and was made anyway. A later
contributor may reasonably read that as the conditions being advisory. The
mitigation is that this record says so explicitly rather than arguing the
conditions were satisfied — which is the failure mode that would actually have
destroyed them.

**Phase 018 is treated as a formality.** The interpreter is already pinned, so a
survey that finds a problem arrives after the decision it was meant to inform.
Section 3 exists to name that in advance, and ADR-0050 states the free-threaded
and prerelease refusals as provisional on exactly this survey.

**Two retitled phases lose their original intent.** Somebody who remembers the old
titles may implement the old scope. The roadmap's amendment block records all four
changes in one place for exactly this reason, and it is where the answer is.

## References

- `ROADMAP.md` — the *Scope amendments* block, which now carries four entries.
- [ADR-0012](0012-phase-003-delivers-architecture-boundaries.md) — the first amendment.
- [ADR-0016](0016-phase-004-absorbs-the-quality-gate-scope.md) — the second, and the warning about a third.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the third, and the four conditions this record fails.
- [ADR-0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md) — what the merged phase actually decided.
- `docs/release/FOUNDATION_ACCEPTANCE.md` — the Phase 017 handoff table, corrected by this amendment.

## Supersedes

Nothing.

## Superseded By

Nothing yet.
