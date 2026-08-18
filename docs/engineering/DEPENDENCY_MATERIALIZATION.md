# Dependency Materialization

Whether the environment `pylock.toml` describes could actually be built on this
machine, from bytes already here. Delivered in Phase 029;
[ADR-0078](../adr/0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md)
records the reasoning.

This is a different question from the one
[`DEPENDENCY_LOCKING.md`](DEPENDENCY_LOCKING.md) answers. That asks whether the
committed lock is internally coherent — a question about a *file*. This asks
whether an environment could be materialized from it — a question about a
*machine*.

---

## The commands

```bash
python -m tools.quality materialize
```

Offline. Reads the lock, hashes whatever is in the wheelhouse, and reports whether
every artefact the declared target needs is present and correct. Writes
`.globin/materialize/materialize-manifest.json`.

```bash
python -m tools.quality.materialize verify
```

The same, spelled as a subcommand.

```bash
python -m tools.quality.materialize cleanroom
```

**REACHES THE INDEX.** Builds a throwaway environment in the platform's temporary
directory and reports what it holds. Not part of any quality command, and
exercised by an integration test marked `external`, `network` and `slow`.

---

## Why it is not in `full`

For the same reason `drift` is not. With an **empty wheelhouse** the verdict is
`unmeasured` and the exit code is `3` — not a failure. Artefacts are hundreds of
megabytes and are not committed, so a fresh clone has established *nothing* rather
than established an absence.

| Wheelhouse | Verdict | Exit |
|---|---|---|
| Empty | `unmeasured` — offline readiness is unestablished | 3 |
| Populated, every artefact correct | `passed` | 0 |
| Populated, an artefact's bytes are wrong | `failed` | 1 |
| Any artefact unhashed, unservable, or source-only under a no-source policy | `failed` | 1 |

The last row is the subtle one. Those three faults fail **even with an empty
wheelhouse**, because fetching would not fix any of them: they are statements
about the lock, not about what has been downloaded.

---

## The cache is not a source of trust; the lock is

An artefact is addressed **by** the digest the lock records. The cache key is the
normalised name, the version, the algorithm, the digest and the filename — and the
filename participates because it carries the PEP 425 platform tags, so there is no
separate platform field to drift from it.

```text
<name>/<version>/<digest[:2]>/<filename>
```

Bytes are re-hashed before use. A file that hashes to something else is not a cache
hit that failed validation; it is a different file that was never under that key.

**A corrupt artefact is left in place and its path reported.** It is not deleted —
removing the evidence of a corruption is how the ability to diagnose it is lost —
and it is not re-fetched, which would be the cache quietly becoming a network
client.

`md5`, `sha1` and `sha224` are refused **by name**, regardless of what any policy
file permits, matching both pip's hash-checking mode and the existing lock gate.

---

## The offline guarantee is structural

`tools/quality/materialize/plan.py` **imports no networking module at all** and
takes the cache's contents as an argument. There is no branch somebody could add
that reaches an index, because the module that decides has no way to reach
anything.

That is the same construction `scripts/bootstrap.ps1` uses when it refuses rather
than falling back, and it is what makes the verdict trustworthy: not a promise
that the code does not fetch, but a module that cannot.

---

## Tags come from the declaration, never from this interpreter

| | Question | Tag source | Same answer on every machine? |
|---|---|---|---|
| This gate | Does an artefact exist serving the **declared** target? | `lock-policy.toml` `[target]` | **Yes** |
| `globin.adapters.dependency.host_tags` | Could **this** interpreter install it? | `packaging.tags.sys_tags()` | No, by construction |

Using `sys_tags()` here would make the gate reject the committed lock on the 3.12
matrix leg. The tags are an **ordered tuple**, not a set, because PEP 425 order
*is* preference — and `packaging.tags.Tag` is deliberately unorderable, which is
the library declining to invent a preference of its own.

---

## Artefact selection is the reference implementation's

`packaging.pylock`'s `Pylock.select` chooses which artefact serves the tags. It is
handed the tags explicitly rather than allowed to default.

**It is all-or-nothing**, which was measured rather than assumed: it raises on the
first package with no serving artefact instead of yielding the rest. A single
unservable distribution is therefore reported as a lock-level problem naming that
package. That is defensible for a gate — an environment that cannot be fully built
is not partly buildable — but it is why `incompatible` is reachable through the
pure planning API and not through this path.

---

## The clean room, and your `.venv`

**The clean room never deletes, recreates or writes to the environment you are
using.** Three independent mechanisms hold that, any one of which alone would be
sufficient:

1. **Location.** The room is created under the platform's temporary directory with
   the prefix `globin-cleanroom-`, which is neither the repository nor the
   user-local runtime tree. `scripts/bootstrap.ps1` is never called and
   `-Recreate` is never invoked; an AST scan asserts the harness evaluates no
   string naming either.
2. **A refusal that names the danger.** `cleanroom_problems` refuses to remove
   anything that is not strictly beneath the scratch root, is the scratch root
   itself, is reachable inside the repository, is a link, or lacks the prefix.
   Four deliberately redundant checks, in the shape
   `tools/quality/runtime/plan.py:deletion_problems` uses so that no recursive
   delete is ever decided anywhere but in a pure function with tests.
3. **Cleanup on every ordinary exit** — return, exception and `KeyboardInterrupt`.

What none of that covers, stated rather than implied: `os._exit`, a kill signal,
and power loss. Nothing in Python cleans up after those. What bounds the damage is
that the residue is a prefixed directory under the system temporary root, which
the platform reclaims and a person can identify at a glance.

An integration test asserts the invariant directly: a decoy `.venv` beside the
scratch root is proved **byte-for-byte unchanged** after both a successful run and
a failing one.

---

## The runtime half

A *running* GLOBIN now carries a dependency inventory. Until Phase 029 it read
every distribution's metadata and **threw the version away**, so an environment two
releases from its lock reported ready.

| State | Meaning |
|---|---|
| `satisfied` | Locked, installed, same release |
| `missing` | Locked and applicable here, not installed |
| `version_mismatch` | Installed at a version the lock does not name |
| `unlocked` | Declared in `pyproject.toml` and absent from the lock |
| `not_applicable` | A marker or `requires-python` excludes it here |

The last one is what stops the inventory crying wolf about a package that was
never meant to be installed on this platform.

Versions are compared as **PEP 440 releases**, so `1.0` and `1.0.0` agree — the
gate compares them as raw text, and the asymmetry is deliberate and pinned by a
contract test so it cannot invert.

`globin bootstrap check --json` publishes the inventory, its fingerprint, and a
`readiness` word — which is what finally gives `DEPENDENCY_UNREADY` a caller after
it sat unset since Phase 027.

**An installed distribution that is neither declared nor locked is not reported**,
and that is a capability limit rather than an oversight: deciding it is unexpected
needs the `seeded` exemption list from `lock-policy.toml`, a file the wheel does
not ship. Without it `pip`, `setuptools` and GLOBIN itself would report as surplus.
`tools/quality/lock` already answers this correctly where the declaration is
readable.

---

## What this does not cover

| Question | Phase |
|---|---|
| What a running GLOBIN does when a component is missing or degraded | 031, delivered — [`DEGRADED_OPERATION.md`](DEGRADED_OPERATION.md) |
| The preflight *suite*, its scheduling and its periodicity | 030, delivered — [`PREFLIGHT_SUITE.md`](PREFLIGHT_SUITE.md) |
| Whether the environment band was drawn at the right granularity | 032, delivered — [`GRANULARITY_REVIEW.md`](GRANULARITY_REVIEW.md) |
| Building `.venv` — still `scripts/bootstrap.ps1`, and only that | 017/020, delivered |
| Repairing drift — still an operator action | 019, delivered |
