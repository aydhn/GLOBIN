# ADR-0084 — Phase 032 widens to deliver the bootstrap provisioning surface

## Status

Accepted — Phase 032. **Date:** 2026-08-19

## Context

`ROADMAP.md` row 032 reads *Environment Consolidation and Phase Gate Review*, and
that document additionally assigns this phase, by name, the question of whether
Phases 017-032 were drawn at a granularity that describes the work.

This phase's brief described something else: a Windows first-run provisioning
surface with check, plan, setup, verify, repair and evidence verbs, install-manager
discovery, an offline-aware dependency path and deterministic provisioning
evidence.

An audit of that brief against the tree found most of it already delivered.
`check`, `verify` and `evidence` are `bootstrap check`, `bootstrap preflight` and
`bootstrap evidence`. Install-manager-versus-legacy-launcher discovery shipped in
Phase 017, disambiguated by the `pymanager` command, with `--install-python` as
its opt-in. The offline dependency path is Phase 029's materialization gate, whose
network fallback is unreachable by import discipline rather than un-taken. The
typed state machine, the exit-code contract and the deterministic evidence are
Phase 021's, extended by Phase 030.

What was genuinely absent: a **plan** produced before anything is applied, a
**declared network policy** as a value, an **incomplete-environment claim** that
makes a false ready state unreachable, and a **bounded process runner**. Nothing
in the programme owned any of the four.

The owner was shown the conflict, the audit, and the choice between delivering the
roadmap's phase alone or delivering both, and chose both.

## Decision

**Phase 032 delivers the environment band closure its title names, and the
bootstrap provisioning surface alongside it.** This is the sixteenth scope
amendment.

ADR-0082 closed by forbidding a sixteenth from citing any prior amendment record
or the running count. This record cites neither, and makes its case from scratch
against the four-part test `ROADMAP.md` states — *nothing displaced, nothing
deferred, no phase owns the work, and the two halves need each other*.

**Nothing deferred: MET.** Both halves ship in the same commit range. The band is
certified by a matrix a gate recomputes, `v0.2.0` is cut against it, the
granularity review is delivered with a contract test binding every count it
states, and the provisioning surface is delivered whole.

**The two halves need each other: MET.** A band cannot be certified as producing
a reproducible host while the path from a clean clone to a working environment is
the one thing no gate recomputes. `ENV-B-01` claims the environment is built
deterministically; before this phase that claim rested on a shell script nothing
exercised end to end. The provisioning surface is what makes five of the
environment-lifecycle criteria measurements rather than assertions.

**Nothing displaced: FAILED.** Phase 291 *Interactive Configuration Wizard* owns
collecting configuration an operator has not supplied, and a provisioning plan
that names what an operator must run is adjacent to that. Nothing here collects
anything, and the boundary is structural rather than intended: no `ActionSpec` may
name a `config.*` or `secrets.*` check in `remedy_for`, and the constructor
refuses one that does.

**No phase owns the work: FAILED.** Phase 291 owns part of it by purpose, as
above. No phase owns it by title, which is the one thing this amendment can say
that the ninth, tenth and fifteenth could not.

**Two of four.** The two it fails are the two eleven of the twelve scored
amendments before it also failed, which is the subject of the granularity review
this phase delivers rather than a defence of this one.

### The review judges the amendment it is

This phase writes both the amendment and the review that scores it. That is stated
in `GRANULARITY_REVIEW.md` rather than worked around, and it is why the review
proposes no replacement for ADR-0021's test and rewrites no roadmap row: a review
conducted inside a phase it must score is not a disinterested one, whatever it
concludes.

## Consequences

**The environment band is closed.** `docs/engineering/environment-acceptance.toml`
carries sixty-one criteria across thirteen capability groups, and one evaluator
recomputes both band matrices — parameterised by `MatrixSpec` rather than copied.

**The package starts a process for the first time.** One module, named by
`tests/architecture/test_process_discipline.py` in both directions.
`dependency-rules.toml` needed no edit: it has always listed `subprocess` among
the I/O-capable modules and always let the adapters layer perform I/O. That the
layer contract permitted this without amendment is evidence the tripwire is the
right shape and size.

**An action declares who performs it.** The packaging forced this: GLOBIN's wheel
holds the package and its metadata and nothing else, so an installed GLOBIN has no
`tools/` to invoke and no `scripts/` to run. What GLOBIN cannot do is reported with
the exact command that can.

**Phase 291 arrives to find its subject adjacent but untouched.** A plan names
what an operator must run; it collects nothing, writes no configuration document
and reaches no credential store.

## Alternatives Considered

**Deliver the roadmap's phase alone and set the brief aside.** The strongest option
on the roadmap's own terms, and the one needing no ADR. Declined by the owner. Its
cost was that the four genuinely-missing capabilities have no owner in the
programme at all, so they would have been deferred indefinitely rather than to a
named phase.

**Deliver the brief alone, leaving row 032 `Planned`.** Would have left the band
unclosed while Phase 033 becomes due immediately after, and would have deferred
the granularity review a seventh time. Declined by the owner.

**Deliver the residue as tooling under ADR-0032.** Declined for the reason ADR-0073
declined it: that record's fourth condition is that the addition adds no runtime
capability, and `globin bootstrap plan` is exactly a runtime capability. An
ADR-0032 addition would have had to stay inside `tools/quality/`, which the package
cannot reach.

**Bring the granularity review forward and let a later phase judge this
amendment.** Not offered, because the review is this phase's by name and deferring
it a seventh time is what the review is about.

## Risks and Trade-offs

**The characteristic failure mode is that Phase 291 arrives and finds its subject
partly built.** The mitigation is structural rather than intentional: the
constructor refuses an action answering a `config.*` check, so the boundary cannot
be crossed by somebody who did not read this record.

**A second risk is specific to the process capability.** The package could not
start a process before this phase and now can. The tripwire is a proxy rather than
a proof — a module handed an open pipe would defeat it — and it is the same proxy
`test_library_discipline.py` uses for the socket, with the same limitation stated
there.

**A third is that `setup` reads as a cold-start command and is not one.** It is
installed into the environment it would create. `PROVISIONING.md` says so in its
first screen, and a contract test asserts the document names
`scripts/bootstrap.ps1`.

## References

- [`../engineering/PROVISIONING.md`](../engineering/PROVISIONING.md) — the operator flow.
- [`../engineering/GRANULARITY_REVIEW.md`](../engineering/GRANULARITY_REVIEW.md) — the review this phase also delivers.
- [`../release/ENVIRONMENT_ACCEPTANCE.md`](../release/ENVIRONMENT_ACCEPTANCE.md) — what the band was certified against.
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the test scored above.
- [ADR-0085](0085-a-plan-is-derived-from-a-report-and-one-module-may-start-a-process.md) — the technical decisions this amendment carries.

## Supersedes

Nothing.

## Superseded By

Nothing.
