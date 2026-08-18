# Architecture Decision Records

An ADR records a decision with lasting consequence: what was decided, the
context that made it necessary, and what it costs. The context matters as much
as the decision. A future contributor who understands only *what* was chosen
will eventually undo it; one who understands *why* can tell whether the reason
still applies.

## Rules

1. **Numbering is contiguous from `0001` and never reused.** Filenames follow
   `NNNN-kebab-case-title.md`. Start from [`TEMPLATE.md`](TEMPLATE.md).
2. **Accepted ADRs are immutable.** A changed decision is written as a *new*
   ADR that supersedes the old one. The superseded record stays, with its status
   updated, so the reasoning history survives.
3. **Every ADR has four sections**, in this order: `## Status`, `## Context`,
   `## Decision`, `## Consequences`. This is checked by
   `tests/contract/test_documentation_contract.py`. Records from 0012 onwards additionally
   carry `## Alternatives Considered`, `## Risks and Trade-offs`,
   `## References`, `## Supersedes` and `## Superseded By`, and that is checked
   too. Earlier records predate those sections and are immutable, so they are
   not retrofitted — see [`TEMPLATE.md`](TEMPLATE.md).
4. **Every ADR is listed in this index**, with the same status the record itself
   states. Both are checked by test.
5. Status is one of: `Proposed`, `Accepted`, `Rejected`, `Deprecated`, or
   `Superseded by ADR-NNNN`.

## When to write one

Write an ADR when a choice constrains future work, is expensive to reverse, or
would otherwise be re-litigated by someone who does not know why it was made.
Do not write one for routine implementation detail — that belongs in code and
its docstrings.

The categories that reliably qualify are structure, non-functional requirements,
dependencies between components, published interfaces, and construction
techniques such as a library or tool the project commits to. See
[`../research/phase_003_sources.md`](../research/phase_003_sources.md) entries
S-04 and S-05.

## Changing a decision

A record is immutable once it is `Accepted` **or** `Rejected`. A rejected record
is kept rather than deleted: it records that the question was asked and
answered, which is what stops the same debate recurring a year later.

To change a decision:

1. Write a **new** ADR with the next contiguous number.
2. Name the record it replaces under its `## Supersedes` heading.
3. In the same commit, set the old record's `## Status` to
   `Superseded by ADR-NNNN` and fill in its `## Superseded By` heading. That
   status edit is the only change an immutable record accepts.
4. Update the status column for both records in the index below.

Doing this in one commit is not tidiness. A test asserts that the two records
point at each other and that the index agrees with both, so a half-finished
supersession fails the build rather than leaving the log quietly inconsistent.

Never edit the reasoning of an accepted record to match a newer view. The value
of the log is that it shows what was believed at the time, which is the only way
a future reader can judge whether the reason still holds.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-project-identity-and-python-first-local-architecture.md) | Project identity and Python-first local architecture | Accepted |
| [0002](0002-binance-global-only-exchange-scope.md) | Binance Global is the only venue in scope | Accepted |
| [0003](0003-zero-budget-open-source-dependency-policy.md) | Zero-budget runtime and open-source dependency policy | Accepted |
| [0004](0004-official-apis-only-no-scraping.md) | Official documented interfaces only; no scraping | Accepted |
| [0005](0005-master-only-git-workflow.md) | Master-only Git workflow | Accepted |
| [0006](0006-product-and-environment-capability-matrix.md) | Binance integration is driven by a product and environment capability matrix | Accepted |
| [0007](0007-autonomous-learning-governance.md) | Autonomous learning is governed by evidence gates | Accepted |
| [0008](0008-immutable-upper-risk-constraints.md) | Upper risk bounds are immutable and outside the search space | Accepted |
| [0009](0009-windows-bat-launchers-as-entry-points.md) | Two Windows BAT launchers are the final user entry points | Accepted |
| [0010](0010-living-documentation-responsibilities.md) | Documentation is a deliverable, kept live by tests | Accepted |
| [0011](0011-documentation-authority-hierarchy.md) | Documentation has an explicit authority order, with code at the top | Accepted |
| [0012](0012-phase-003-delivers-architecture-boundaries.md) | Phase 003 delivers architecture boundaries; static analysis moves to Phase 013 | Accepted |
| [0013](0013-modular-monolith-as-the-initial-architecture.md) | GLOBIN is a modular monolith in a single Python distribution | Accepted |
| [0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) | Five layers with dependencies pointing inward, enforced by a machine-readable contract | Accepted |
| [0015](0015-single-composition-root-and-no-import-time-side-effects.md) | Dependencies are wired in one composition root, and importing performs no work | Accepted |
| [0016](0016-phase-004-absorbs-the-quality-gate-scope.md) | Phase 004 absorbs the quality-gate scope from Phase 013 | Accepted |
| [0017](0017-test-taxonomy-as-directories.md) | Test level is decided by directory, and `tests` is a package | Accepted |
| [0018](0018-quality-toolchain-and-explicit-strictness.md) | The quality toolchain is pinned, and strictness is written out flag by flag | Accepted |
| [0019](0019-single-quality-entrypoint.md) | One command table defines the checks, and every caller reads it | Accepted |
| [0020](0020-verification-only-continuous-integration.md) | Continuous integration verifies, with least privilege and pinned actions | Accepted |
| [0021](0021-phase-005-widens-to-include-the-test-foundation.md) | Phase 005 widens to deliver the error taxonomy and the deterministic test foundation | Accepted |
| [0022](0022-error-taxonomy-rooted-in-one-type.md) | One error root, five categories chosen by who must act, and no builtin inheritance | Accepted |
| [0023](0023-property-based-testing-as-a-sixth-taxonomy-level.md) | Property-based testing is a sixth taxonomy level, with two Hypothesis profiles | Accepted |
| [0024](0024-tests-are-offline-and-isolated-by-construction.md) | Tests are offline and process-isolated by construction, not by convention | Accepted |
| [0025](0025-structured-logging-is-a-redacted-domain-event.md) | A log record is a domain event that redacts itself, emitted through a port | Accepted |
| [0026](0026-correlation-is-bound-explicitly-not-ambiently.md) | Correlation is bound explicitly, and the timestamp belongs to the adapter | Accepted |
| [0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md) | Configuration is a frozen dataclass validated at one boundary, and the dataclass is the schema | Accepted |
| [0028](0028-configuration-layers-override-last-wins-and-carry-their-origin.md) | Configuration layers are flat, override last-wins, carry their origin, and cannot remove a setting | Accepted |
| [0029](0029-a-severity-threshold-is-a-decorating-sink.md) | A severity threshold is a decorating sink, not a field on a sink or a check in the logger | Accepted |
| [0030](0030-domain-values-are-denominated-wrappers-over-decimal.md) | Domain values are denominated frozen wrappers over `Decimal`, never subclasses of it | Accepted |
| [0031](0031-value-types-compare-but-do-not-compute.md) | Value types compare but do not compute; a wrong type returns `NotImplemented` and a wrong unit raises | Superseded |
| [0032](0032-verification-tooling-may-be-added-outside-phase-scope.md) | Verification tooling may be added outside phase scope, under six conditions | Accepted |
| [0033](0033-mutation-testing-is-a-repository-native-ast-harness.md) | Mutation testing is a repository-native `ast` harness gated by a committed survivor set | Accepted |
| [0034](0034-time-is-injected-and-internal-time-is-utc.md) | Time is an injected clock behind two ports, and internal time is UTC | Accepted |
| [0035](0035-milliseconds-are-a-floored-projection.md) | Milliseconds are a floored projection, not the representation | Accepted |
| [0036](0036-test-execution-is-sharded-by-a-stable-digest-not-by-a-plugin.md) | Test execution is sharded by a stable digest, not by a plugin | Accepted |
| [0037](0037-arithmetic-is-exact-or-refused-under-an-explicit-context.md) | Arithmetic is exact or refused, under an explicitly built context, and rounding is always an argument | Accepted |
| [0038](0038-a-tick-size-and-a-step-size-are-one-undenominated-increment.md) | A tick size and a step size are one undenominated `Increment`, aligned by `divmod` | Accepted |
| [0039](0039-identifiers-register-kinds-not-instances.md) | Identifiers register kinds, not instances, and the registry is a function | Accepted |
| [0040](0040-evidence-records-every-gate-and-its-schema-version-is-a-contract.md) | Evidence records every gate, and its schema version is a compatibility contract | Accepted |
| [0041](0041-serialization-is-exact-or-refused-and-a-version-is-refused-when-unknown.md) | Serialization is exact or refused, and an unknown version is refused rather than read | Accepted |
| [0042](0042-one-aggregate-check-decides-a-run-and-the-artifact-digest-lives-outside-the-artifact.md) | One aggregate check decides a run, and the artifact digest lives outside the artifact | Accepted |
| [0043](0043-ci-trust-is-declared-in-a-manifest-and-every-job-is-bounded.md) | CI trust is declared in a manifest the workflow is compared against, and every job is bounded | Accepted |
| [0044](0044-dependency-review-is-a-written-process-with-a-generated-inventory.md) | Dependency review is a written process over a generated inventory, and the SBOM is generated here | Accepted |
| [0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) | A platform capability is a recorded state, never a pass | Accepted |
| [0046](0046-the-repository-is-public-and-that-changes-the-threat-model.md) | The repository is public, and that changes the threat model rather than only the settings | Accepted |
| [0047](0047-repository-governance-is-declared-once-and-validated-offline.md) | Repository governance is declared once and validated offline | Accepted |
| [0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) | A secret lives outside the tree, and is redacted before a record exists | Accepted |
| [0049](0049-a-version-has-one-source-and-a-release-is-frozen-evidence.md) | A version has one source, and a release is frozen evidence | Accepted |
| [0050](0050-the-runtime-is-a-declared-contract-and-venv-is-its-only-environment.md) | The runtime is a declared contract checked against the host, and `.venv` is its only environment | Accepted |
| [0051](0051-phase-017-absorbs-interpreter-pinning-and-the-environment-lifecycle.md) | Phase 017 absorbs interpreter pinning and the environment lifecycle, and this is not covered by precedent | Accepted |
| [0052](0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md) | Wheel availability is a recorded survey whose verdict is recomputed, and a gap is owned rather than fixed | Accepted |
| [0053](0053-drift-is-measured-against-an-accepted-baseline-and-repair-is-a-classification.md) | Drift is measured against an accepted baseline, and repair is a declared classification rather than an inferred one | Accepted |
| [0054](0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md) | The toolchain is locked with PEP 751, the runtime lock is Phase 021's, and the lock's verdict is recomputed | Accepted |
| [0055](0055-the-first-runtime-dependencies-are-introduced-and-globin-becomes-installed.md) | The first runtime dependencies are introduced, and GLOBIN becomes an installed application | Accepted |
| [0056](0056-phase-021-widens-to-deliver-the-application-bootstrap.md) | Phase 021 widens to deliver the application bootstrap, and this is the fifth amendment | Accepted |
| [0057](0057-phase-022-widens-to-deliver-the-runtime-filesystem-and-lifecycle.md) | Phase 022 widens to deliver the runtime filesystem and lifecycle, and this is the sixth amendment, and the weakest | Accepted |
| [0058](0058-the-scientific-stack-is-verified-by-measurement-and-stays-in-the-approximate-regime.md) | The scientific stack's verdict is recomputed from measurement, and the stack stays in the approximate regime | Accepted |
| [0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md) | The mutable runtime tree is user-local, its state is published atomically, and one coordinator is proved by a lock rather than by a file | Accepted |
| [0060](0060-gpu-capability-is-detected-and-the-runtime-explains-itself.md) | GPU capability is detected as a recorded state, the runtime is given diagnostics, and this is the seventh amendment | Accepted |
| [0061](0061-phase-024-widens-to-deliver-runtime-health-and-support-bundles.md) | Phase 024 widens to deliver runtime health and support bundles, and this is the eighth amendment | Accepted |
| [0062](0062-workload-benefit-is-measured-and-a-timing-is-not-evidence-of-reproducibility.md) | Workload benefit is measured against a declared contract, and a timing is not evidence of reproducibility | Accepted |
| [0063](0063-a-support-bundle-is-allowlist-first-self-validating-and-atomically-published.md) | A measurement that was not taken is never zero, and a support bundle is allowlist-first, self-validating and atomically published | Accepted |
| [0064](0064-phase-025-widens-to-deliver-the-runtime-watchdog.md) | Phase 025 widens to deliver the runtime watchdog alongside TA-Lib, and this is the ninth amendment | Accepted |
| [0065](0065-liveness-is-monotonic-and-escalation-is-bounded-from-the-stall.md) | Liveness is a monotonic sequence rather than a timestamp, and escalation is bounded from the stall rather than from the request | Accepted |
| [0066](0066-a-stack-may-be-published-once-its-paths-are-reduced-and-it-stays-out-of-a-bundle.md) | A stack may be published once its paths are reduced and it stays out of a support bundle | Accepted |
| [0067](0067-phase-026-widens-to-deliver-the-telemetry-foundation.md) | Phase 026 widens to deliver the telemetry foundation, and this is the tenth amendment | Accepted |
| [0068](0068-telemetry-is-provider-neutral-and-cardinality-is-bounded-by-construction.md) | Telemetry is provider-neutral, and cardinality is bounded by construction rather than policed at runtime | Accepted |
| [0069](0069-configuration-is-derived-rather-than-searched-and-a-profile-names-a-document.md) | Configuration is derived rather than searched, and a profile names a document rather than an environment | Accepted |
| [0070](0070-phase-027-widens-to-deliver-the-loopback-diagnostics-surface.md) | Phase 027 widens to deliver the loopback diagnostics surface, over the roadmap's own refusal | Accepted |
| [0071](0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md) | Configuration precedence is one declared order, and an environment variable is a derived name | Accepted |
| [0072](0072-the-diagnostics-surface-is-loopback-only-read-only-and-bounded-by-construction.md) | The diagnostics surface is loopback-only by type, read-only, and bounded by construction | Accepted |
| [0073](0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md) | Phase 028 widens to deliver the environment capability inventory | Accepted |
| [0074](0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) | The secret store is the Windows Credential Manager, and rotation is constructed rather than inherited | Accepted |
| [0075](0075-native-architecture-is-measured-through-one-adapter-and-a-fingerprint-excludes-what-moves.md) | Native architecture is measured through one adapter, and a fingerprint excludes what moves | Accepted |
| [0076](0076-phase-029-widens-to-deliver-the-dependency-attestation.md) | Phase 029 widens to deliver the dependency attestation | Accepted |
| [0077](0077-a-credential-is-collected-at-a-console-and-a-permission-is-declared-rather-than-verified.md) | A credential is collected at a console, and a permission is declared rather than verified | Accepted |
| [0078](0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md) | The second lock reader is the reference implementation, and a cache is not a source of trust | Accepted |
| [0079](0079-phase-030-widens-to-deliver-the-configuration-evidence-surface.md) | Phase 030 widens to deliver the configuration evidence surface | Accepted |
| [0080](0080-a-check-declares-whether-its-answer-survives-the-run.md) | A check declares whether its answer survives the run | Accepted |
| [0081](0081-configuration-explains-itself-through-two-fingerprints-and-one-manifest.md) | Configuration explains itself through two fingerprints and one manifest | Accepted |
| [0082](0082-phase-031-widens-to-deliver-the-user-scoped-secret-vault.md) | Phase 031 widens to deliver the user-scoped secret vault | Accepted |
| [0083](0083-a-second-secret-mechanism-is-admitted-by-arithmetic-and-carries-its-own-integrity-check.md) | A second secret mechanism is admitted by arithmetic and carries its own integrity check | Accepted |
| [0084](0084-phase-032-widens-to-deliver-the-bootstrap-provisioning-surface.md) | Phase 032 widens to deliver the bootstrap provisioning surface | Accepted |
| [0085](0085-a-plan-is-derived-from-a-report-and-one-module-may-start-a-process.md) | A plan is derived from a report, and one module may start a process | Accepted |

## Relationship to other documents

ADRs record *decisions*. Durable technical reasoning that is not a single
decision belongs in [`../ARCHITECTURE_PRINCIPLES.md`](../ARCHITECTURE_PRINCIPLES.md).
Rules about how work is carried out belong in
[`../engineering/`](../engineering/ENGINEERING_CONTRACT.md). Evidence supporting
a decision belongs in [`../research/`](../research/), cited from the ADR rather
than restated inside it.

Where an ADR and another document appear to disagree, the precedence order in
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) applies.
