# ADR-0056 — Phase 021 widens to deliver the application bootstrap, and this is the fifth amendment

## Status

Accepted — Phase 021.

**Date:** 2026-08-16

## Context

GLOBIN had no process surface. `src/globin/` was a library reachable only through
`pythonpath`, every command was a gate under `tools/quality/`, and nothing could
answer the question a launcher will eventually have to ask: *may this process
start?* Phases 017 to 020 built five separate answers — a host contract, a wheel
survey, a drift baseline, a lock, and a configuration model from Phase 007 — and
left them unassembled.

[ADR-0009](0009-windows-bat-launchers-as-entry-points.md) already fixes the
eventual user-facing entry points as two BAT files, and gives them a contract
that includes locating the repository, validating prerequisites, and running
health checks before anything starts. Phases 289-304 implement those launchers.
Nothing was scheduled to build the machinery they would call.

The pressure to build it now came from the other half of this phase. A console
entry point exists only once something is installed; installing GLOBIN pulls
`project.dependencies`; and `tools/quality/lock`'s environment comparison
immediately reports the newly-installed project as a distribution no lock
resolved. The three could not be delivered separately, and the owner chose to
deliver both halves in Phase 021 rather than split them across a phase boundary
that would have left each half unusable.

**`ROADMAP.md` does not give Phase 021 this work**, and four planned phases own
parts of it by name: 026 (configuration file layout and profiles), 027
(environment-variable and profile resolution), 028 (local secret storage), and
030 (bootstrap health check suite).

## Decision

**Phase 021 additionally delivers the application bootstrap**, and this is the
**fifth roadmap scope amendment**. `ROADMAP.md` records the four before it, and
[ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) set a
four-part test for whether an amendment is covered by precedent. This one is
recorded honestly against that test rather than argued past it:

| ADR-0021's test | This amendment |
|---|---|
| Nothing displaced | **Fails.** The core of Phase 030's preflight suite arrives here. |
| Nothing deferred | Holds. Nothing Phase 021 owned is postponed. |
| No phase owns the work | **Fails.** Phase 030 owns a health-check suite by name. |
| The two halves need each other | Holds, and not by construction — the lock gate refused the install until both existed. |

Two of four, as the fourth amendment also failed two. ADR-0051 said a fifth has a
higher bar than a fourth did; the bar this clears is the fourth criterion, which
the fourth amendment could not claim at all.

**The amendment is narrowed by what it refuses to build.** The bootstrap delivers
only what no phase owns — one entry point, a deterministic pipeline, a typed
runtime context, an exit-code contract, a runtime path contract, and
secret-safe evidence — and leaves the rest as a registry other phases add to.
`globin.domain.bootstrap.checks` is a function returning a tuple, so Phases 026
to 030 register their checks rather than rewriting this one.

**No placeholder check is registered.** Recording a check whose subject does not
exist as `unmeasured` would be claiming a measurement nobody attempted. The
twelve registered checks are the ones that can be answered truthfully today;
`config.profile` (026), `config.sources` (027), `secrets.store` (028),
`secrets.prompt` (029) and the wider preflight suite (030) are named in
`docs/engineering/BOOTSTRAP.md` with their owning phase and are absent from the
registry.

**`secrets.required` passes vacuously and says so.** GLOBIN holds no credential,
so the set of references a start-up must resolve is empty and the claim over it
is true. The summary states that this is why, because a vacuous truth and a
skipped check are indistinguishable in a log and mean opposite things.

**Nothing under `src/globin/` carries a credential-shaped name.**
`docs/security/SECRET_STORE_CONTRACT.md` §1 gives the reference type to Phase 028
and forbids the name until `README.md` says the capability exists. This phase
therefore measures readiness and holds no reference type; a contract test
enforces the naming rule.

**The five layers are unchanged.** `src/globin/cli/` would have been a sixth
package, requiring `docs/architecture/dependency-rules.toml`, the `Layer` enum
and [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) to move together.
The bootstrap is instead one module per existing layer, with the entry point in
`globin/runtime/` — which is the composition root, and where an entry point
belongs.

**A declared path is a string; a published path is a `RecordedPath`.** The domain
may import no I/O-capable module, and `pathlib` is one, so `RuntimePaths`
declares the runtime tree relative to the project root and the adapter is the
only thing that knows where that root is. A path that must be published becomes a
three-outcome type enforced at construction — inside with a relative spelling,
outside with a fingerprint only, or absent — so an absolute path cannot reach the
evidence by being forgotten.

**Fail-closed is a property of a type.**
`globin.domain.bootstrap.BootstrapOutcome` refuses to hold a `RuntimeContext`
unless every registered check passed. A run that failed cannot hand anything
downstream because the object that would authorise it does not exist, so there is
no flag to check and no convention to remember.

**The exit code is a contract.** `0`, `1`, `2` and `3` keep the meanings every
gate under `tools/` gives them; `10` upwards name the failure class, one code per
class, pinned to literals by a contract test. The earliest failing check decides,
and unmeasured outranks failed.

**A gate stops; a diagnostic does not.** `bootstrap check` refuses at the first
problem, `doctor` measures everything it still can. One pipeline, one report
type, one set of judgements — only the stopping rule differs, which is what stops
the two from becoming two descriptions of one host.

**Out of scope.** Every Binance interface, transport, credential and launcher.
This phase reaches no network of any kind, and a contract test asserts the
adapter imports nothing from `tools/`.

## Consequences

The roadmap's Phase 030 is now smaller than its title suggests. Whoever reaches
it will find the frame built and the registry waiting, and must read this record
to know why — which is the cost of an amendment that displaces work.

GLOBIN must now be installed to be fully usable, which it never was before.
`python -m globin` still works from a source tree, and `globin doctor` reports
`project.identity` as a warning naming the missing install rather than failing —
but the console script genuinely does not exist until `bootstrap.ps1` has run.

Every future check must supply a stable identifier, a category, an exit code and
a remediation sentence, and adding one changes a contract test. That is friction,
and it is the friction that keeps the exit codes meaning something.

`docs/engineering/BOOTSTRAP.md` is now a document that must be kept true, and it
carries the handoff Phase 022 reads.

## Alternatives Considered

**Defer the bootstrap to Phase 030 and ship only the dependencies.** The honest
minimum. Rejected because the console entry point is what makes the install worth
performing, and without an install the runtime lock is a file nobody installs
from — the phase would have delivered a lock and no way to know it was honoured.

**Build the bootstrap and defer the dependencies.** Symmetrically possible.
Rejected because `[project.scripts]` without an install is a declaration nothing
creates, and installing GLOBIN is what makes `project.dependencies` non-empty in
practice even when it is empty in the manifest.

**Register the 026/027/028 checks now as `unmeasured` placeholders.** It would
have made the registry look complete and the amendment look smaller. Rejected
because an unmeasured check claims a measurement was attempted, and five checks
that never attempt anything would make `unmeasured` mean "not built yet" — which
is the one thing ADR-0045 spent effort making it not mean.

**Put the CLI in a sixth package, `src/globin/cli/`.** The obvious layout, and
what the phase brief asked for. Rejected because it would move ADR-0014, the
dependency contract and the `Layer` enum together for a module the composition
root already has a place for.

**Give `doctor` and `bootstrap check` separate implementations.** Each is simpler
alone. Rejected for the reason the repository already refuses two SBOM
generators: two descriptions of one host eventually disagree, and the one that
disagrees is the one nobody ran.

## Risks and Trade-offs

**The characteristic failure mode is registry rot** — Phases 026 to 030 finding
the seam does not fit and adding a second check mechanism beside it. The
observable signal is a check performed outside `checks()`, or a second exit-code
table. Nothing prevents it; the contract test only holds what exists.

**The second is that the exit-code contract ossifies too early.** Thirteen codes
were chosen before any launcher branches on them, and Phases 289-304 may want
distinctions this does not draw. The signal is a launcher parsing the summary
text because the code was not specific enough. Adding a code is cheap; changing
one is not, which is the asymmetry worth knowing about now.

**The third is that this amendment reads as precedent.** It failed two of
ADR-0021's four criteria, and the record above exists so that a sixth amendment
has to make its own argument rather than cite this one. A signal that it has gone
wrong is an amendment citing "as in Phase 021" without restating the test.

Confidence is high on the layering and the fail-closed property, and moderate on
the check registry, which has one consumer and four hypothetical ones.

## References

- [ADR-0009](0009-windows-bat-launchers-as-entry-points.md) — the launchers this builds machinery for
- [ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) — the layer contract this does not change
- [ADR-0015](0015-single-composition-root-and-no-import-time-side-effects.md) — where the wiring lives
- [ADR-0019](0019-single-quality-entrypoint.md) — why the parser is written out
- [ADR-0021](0021-phase-005-widens-to-include-the-test-foundation.md) — the four-part amendment test
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — why `unmeasured` is never a pass
- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — redaction before a record exists
- [ADR-0051](0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) — the fourth amendment
- [ADR-0055](0055-the-first-runtime-dependencies-are-introduced-and-globin-becomes-installed.md) — the other half of this phase
- [`../engineering/BOOTSTRAP.md`](../engineering/BOOTSTRAP.md) — the lifecycle, the CLI and the handoff
- [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md) — §1, and why nothing here is named after a credential

## Supersedes

None.

## Superseded By

None.
