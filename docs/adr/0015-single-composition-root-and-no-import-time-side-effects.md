# ADR-0015 — Dependencies are wired in one composition root, and importing performs no work

## Status

Accepted — Phase 003.

**Date:** 2026-08-14

## Context

[ADR-0014](0014-layered-ports-and-adapters-and-inward-dependencies.md) says the
inner layers depend on ports rather than on implementations. That leaves an
unanswered question: *who chooses the implementation?* If the answer is "each
module, wherever it needs one", the layering is decorative — an
`application` module that constructs its own adapter has imported it, and the
boundary is gone.

There is a second, quieter question with the same shape. Python executes a
module's top level on first import. A module-level HTTP client, a
`logging.basicConfig()` call, a credential read or a file handle therefore turns
`import globin` into an action rather than a declaration.
[`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
invariant 5 already prohibits this, but nothing checked it, and the failure mode
is unpleasantly indirect: the test suite starts depending on collection order,
and a machine without a particular file can no longer import the package at all.

Both questions matter more here than in most projects. GLOBIN will eventually
hold credentials, and ADR-0004 forbids committing them; a credential read at
import time would run during test collection on any machine that has one. The
system must also be exercisable against fakes (ADR-0006), which is impossible if
construction happens where it cannot be intercepted.

## Decision

**1. There is one composition root**, `globin.runtime`. It is the only place a
concrete adapter is constructed. Everywhere else, an implementation arrives as a
constructor argument typed as a port.

**2. Composition happens in plain functions**, not in a dependency injection
container. A function that constructs and returns an object graph is typed,
traceable in a stack trace, and readable top to bottom. A container would add a
runtime dependency, which ADR-0003 makes an asserted invariant rather than a
preference, and would move the graph into reflection where neither `mypy` nor a
reader can follow it.

**3. Importing a layer module performs no work.** No network call, no file
read or write, no credential access, no environment validation, no subprocess,
no thread or process start, no scheduler, no GPU initialisation, no model load,
no client construction, and no logging handler installation.

**4. The rule is checked, not merely stated.** The syntax tree of every layer
module is inspected and any call that would evaluate at import time is a test
failure. The check is stricter than the rule — it rejects *all* import-time
calls, not only dangerous ones — because deciding whether an arbitrary call
reaches the outside world is undecidable, whereas this is exact and its failures
are easy to fix. It applies to the layer packages only;
`project_contract.py` and `roadmap.py` build frozen constants at import, which
is inert but predates the rule.

**5. Configuration is not read by the inner layers.** A use case receives values;
it does not go looking for them. Which environment variable or file supplied a
value is a `runtime` concern, and the typed configuration model itself belongs
to Phase 007.

**6. Secrets never reach the inner layers in raw form.** Retrieval is an adapter
responsibility, `domain` and `application` hold no API key, and no credential is
read at import under any circumstances. This states the boundary only; secret
storage, redaction and least-privilege key usage are designed in Phase 015.

## Consequences

- Constructing anything real requires going through `runtime`, so the answer to
  "what is this program actually made of?" is one file rather than a search.
- Tests can build a use case directly from fakes without patching module
  globals, because there are no module globals to patch.
- Import stays cheap and deterministic. `import globin` behaves identically on a
  machine with no credentials, no network and no data directory.
- A small ongoing cost: constants that would naturally be computed at module
  level must be expressed as literals or moved into functions. The composition
  root holds its paths as strings rather than as `Path` objects for exactly this
  reason, which is mildly awkward and entirely deliberate.
- Wiring is manual. As the object graph grows, `runtime` grows with it, and
  there will be a phase where a container looks attractive. The trade is
  explicitness for verbosity, and it should be re-argued rather than drifted
  into.
- The import-time check cannot see everything. A function called from a module
  that is itself imported for its side effects would evade it; so would work
  performed inside a class decorator. It catches the common accident, not a
  determined one.

## Alternatives Considered

**Let each module construct what it needs.** Rejected. It is the default in
Python and it is why so many codebases cannot be tested without a network. It
also silently deletes ADR-0014: a module that constructs an adapter has imported
one.

**Use a dependency injection container.** Rejected on two independent grounds.
It would be a runtime dependency in a project whose empty dependency list is an
asserted invariant, and it would relocate the object graph from code into
configuration and reflection, where static typing cannot check it. Reconsider if
manual wiring genuinely becomes unmanageable — but the threshold is
unmanageable, not tedious.

**Module-level singletons initialised lazily on first use.** Rejected. Lazy
initialisation removes the import-time cost but keeps the worse problem: the
choice of implementation is still made inside the module that uses it, and it
becomes order-dependent and awkward to reset between tests.

**Permit import-time work behind an `if` guard on an environment variable.**
Rejected. It makes import behaviour depend on the machine, which is precisely
the property being removed, and it is how a package becomes unimportable in the
one environment nobody tested.

**Check import purity by importing modules in a subprocess and observing
effects.** Rejected as the primary mechanism. Observing filesystem and network
effects reliably is far more machinery than static analysis, and it would only
cover the code paths that actually execute. Static inspection sees every module
whether or not anything imports it.

## Risks and Trade-offs

The strictness is the trade. Rejecting every import-time call will occasionally
reject something harmless — a computed constant, a precompiled regular
expression — and the fix will sometimes be to make the code slightly less
natural. That is a real cost paid in exchange for a rule that needs no
judgement to apply.

The deeper risk is that the composition root becomes the place where complexity
hides. A single function wiring five objects is clear; the same function wiring
sixty is a different artefact, and "one composition root" can degrade into "one
enormous function nobody reads". The signal to watch for is `runtime` acquiring
branching logic about *what* to build rather than merely building it; when that
appears, the answer is to split composition by subsystem while keeping it inside
`runtime`, not to scatter construction back into the layers.

## References

- [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
  — invariant 5, no hidden global state, which this record makes checkable.
- [`../architecture/README.md`](../architecture/README.md) — the layer
  responsibilities and the import-time rule in prose.
- [`../../src/globin/runtime/composition.py`](../../src/globin/runtime/composition.py)
  — the worked example.
- [`0014-layered-ports-and-adapters-and-inward-dependencies.md`](0014-layered-ports-and-adapters-and-inward-dependencies.md)
  — the boundaries this record keeps intact.
- [`0003-zero-budget-open-source-dependency-policy.md`](0003-zero-budget-open-source-dependency-policy.md)
  — why no injection framework is added.

## Supersedes

None.

## Superseded By

None.
