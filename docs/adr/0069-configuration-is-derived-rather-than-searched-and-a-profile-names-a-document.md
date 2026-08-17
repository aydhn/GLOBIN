# ADR-0069 — Configuration is derived rather than searched, and a profile names a document rather than an environment

## Status

Accepted — Phase 026.

**Date:** 2026-08-17

## Context

[ADR-0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md) built
a typed configuration model and left three questions open by name: where documents
live, which are consulted and in what order, and how a profile is selected.
`adapters/configuration.py` states the rule that kept those separable — *"the path
is given, never guessed"* — and warns that searching for a file here would settle
Phase 026's decisions by accident.

Phase 026 answers the first question. Phase 027 answers the second. The difficulty
is that the two are easy to conflate: any implementation that returns "the
configuration" has, by returning it in some order, decided precedence.

There is also a naming problem the roadmap creates. Row 026 names four profiles —
paper, demo, testnet and live — and three of those are Binance vocabulary. Phase
035 decides what an environment *is* and Phase 036 which product and environment
pairs are usable, so a Phase 026 implementation that made `testnet` mean something
would answer their question six phases early.

## Decision

**1. Configuration lives in the checkout, under `config/`.** It is a third kind of
location and neither existing tree is right for it. `.globin/` is evidence about
this repository, Git-ignored and regenerable — an operator's configuration lost on
a fresh clone is not configuration. The user-local runtime tree is state about this
machine, and every area of it is documented **safe to delete**; an authored document
there would be the first un-deletable thing in a tree whose whole design rests on
disposability, which is ADR-0059's own named characteristic failure arriving early.

Configuration is neither evidence nor state: it is **authored operator intent**,
hand-written, and the one thing in the system whose loss cannot be recovered by
re-running anything. It also must be **diffable**, because a document that will one
day select live trading has to be reviewable. This fills the `RuntimePaths.config`
reservation Phase 021 declared and `REPOSITORY_LAYOUT.md` has been holding open.

**2. Nothing searches. Given a layout and a profile, the candidate documents are a
pure function of the two.** No upward walk, no fallback chain, no
first-one-that-exists. Each of those is a *precedence* decision, and precedence is
Phase 027's.

**3. `documents_for` returns a MAPPING, never a sequence.** A tuple has an order and
a reader would read that order as precedence. The return type is where the boundary
is held, rather than a comment asking people not to infer one.

**4. A profile names a document. It does not name an environment.** The boundary is
held by a mechanism that already exists rather than by a new refusal: `as_config`
rejects every key outside `known_keys()`, and not one of those keys can say anything
about a venue, a URL or a product. **A profile document is structurally incapable of
asserting what an environment is**, which is stronger than a rule anybody has to
remember.

**5. The four documents set nothing, and that is the deliverable rather than a
shortfall.** GLOBIN does not trade, so no setting differs between the four for a
reason anybody could defend today. Writing one in would invent a difference to
justify the files and encode a belief about how they differ in a document nobody
would think to look in. `CONFIGURATION_POLICY.md` already describes this shape — *"a
source with nothing to say still returns a layer"* — and a contract test folds all
five documents over the declared defaults and asserts the result **is** the declared
defaults. The day one of them sets a value, that test fails and somebody has to say
why.

**6. The domain bounds a profile name's SHAPE; the composition root names the
INSTANCES.** `demo`, `testnet` and `live` are venue vocabulary, and
`tests/architecture/test_identifier_discipline.py` refuses venue vocabulary as a
live constant anywhere under `globin.domain` — because a set of environment names
compiled into the innermost layer answers Phase 035's question quietly and in the
wrong place. So `domain/config_layout.py` states what a profile name may look like
and refuses anything else, and `composition.PROFILES` supplies the four. That is
`identifiers.py`'s kinds-not-instances discipline applied to a second subject, and
the existing code had already reached the same conclusion: `DEFAULT_PROFILE` has sat
in the composition root since Phase 022.

**7. An unrecognised profile name is REFUSED, never matched to a neighbour and never
defaulted.** ADR-0006's "never downgraded to production" read at the level of a
filename. Case and surrounding whitespace are forgiven because both are accidents of
a launcher argument's transport; nothing else is. Uppercase is refused inside the
name because a profile becomes a filename and Windows compares filenames
case-insensitively, so `Paper` and `paper` would name one document while comparing
unequal everywhere else.

**8. `DEFAULT_PROFILE` is `paper`, and it must never be `live`.** ADR-0006's rule
read in the direction nobody writes down: "never downgraded to production" also
means never silently *upgraded* to it, and a default is the quietest upgrade there
is.

**9. `build_configuration` is unchanged, deliberately.** It still passes no sources
and production still runs on declared defaults. Phase 026 defines where documents
live and what a profile is; Phase 027 implements precedence between defaults, files,
environment variables and launcher selection. Delivering on a seam rather than on a
driver is the same shape the watchdog was delivered in, and stating it here stops it
reading as an incomplete delivery.

**10. TOML, and the argument is not merely that it is already here.** `tomllib` is
**read-only**, so GLOBIN can never write a configuration file back and an operator's
comments, ordering and formatting cannot be destroyed by the program. A format the
program can rewrite is one that eventually loses somebody's comment explaining why a
number is what it is.

## Consequences

- `config/` exists with six documents: a base, four profiles, and a Git-ignored
  `config/local/` for an operator's own overrides — defence in depth rather than a
  licence, since `SECURITY_BASELINE.md` says a secret never arrives through
  configuration at all.
- The ignore rule is **anchored** (`/config/local/`), because a bare `local/` would
  match at every depth — how Phase 018 silently lost a whole package.
- `DEFAULT_PROFILE` changes from `"default"` to `"paper"`, so `run/instance.json`
  and every health snapshot record a different value.
- `REPOSITORY_LAYOUT.md`'s claim that there is one machine-readable configuration
  file needs qualifying: `pyproject.toml` configures the *tools*, `config/`
  configures *GLOBIN*, and a tool's settings never go in the latter.
- A limitation worth stating: `find_project_root` walks up from the working
  directory, so an installed `globin` run from an arbitrary directory finds no root
  and therefore no configuration — and runs on declared defaults, exactly as today.
  The launchers Phase 289 owns set the working directory inside the checkout.

## Alternatives Considered

**Put configuration in the user-local runtime tree.** Rejected on decision 1's
reasoning: every area there is documented safe to delete, and an authored document
would break that guarantee for the whole tree.

**Search upward for a configuration file, as most tools do.** Convenient, and it is
what a developer expects. Rejected because a search order *is* a precedence, and
precedence is Phase 027's decision — settling it here by implementation would be the
accident `adapters/configuration.py` warns about by name.

**Give each profile one differing setting**, so the files are visibly distinct.
Rejected: choosing `INFO` for live and `DEBUG` for paper encodes a belief about how
the four differ, which is Phase 035's question arriving early in a file nobody would
look in.

**Make `Profile` a four-member enum in the domain.** The first implementation, and
the architecture tripwire refused it. Recorded here because the refusal was right
and the reason is not obvious: three of the four names are venue vocabulary, and the
innermost layer is the worst place to answer a question about what a venue offers.

## Risks and Trade-offs

**The characteristic failure mode is that Phase 027 finds the mapping return type
inconvenient** and replaces it with an ordered sequence, at which point the boundary
this record holds becomes a comment. **The observable signal** is a change to
`documents_for`'s return type; that should be read as a change to this decision
rather than as a refactor.

**A second risk is that four empty documents read as unfinished work** and somebody
fills them in to make the phase look complete. The contract test is what makes that
a deliberate act: it fails the moment any of them sets a value.

**A third is the working-directory limitation.** It is real, it is documented, and
it is invisible until somebody runs an installed `globin` from elsewhere and gets
declared defaults without being told. `doctor` reporting which documents were
located would close it, and is left to Phase 027 with the rest of the resolution
question.

## References

- [`../engineering/CONFIGURATION_LAYOUT.md`](../engineering/CONFIGURATION_LAYOUT.md)
  — the layout's own document.
- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the settings register.
- [ADR-0006](0006-product-and-environment-capability-matrix.md) — the rule
  decisions 7 and 8 apply.
- [ADR-0027](0027-configuration-is-a-frozen-dataclass-validated-at-the-boundary.md) —
  the model this completes.
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md)
  — the tree decision 1 declines to use.

## Supersedes

None.

## Superseded By

None.
