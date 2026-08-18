# Dependency Locking

How this repository's dependency set is resolved, recorded, verified, upgraded and
audited, and what the record deliberately does not claim.

[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) owns whether a dependency may
be adopted at all. This document owns what happens to one that has been: how the
version that will actually be installed is fixed, and how anybody checks that the
fixing worked. The decision behind it is
[ADR-0054](../adr/0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md);
the external evidence is in
[`../research/phase_020_sources.md`](../research/phase_020_sources.md).

---

## The problem this solves

Seven development tools are declared in `pyproject.toml`, each with a lower bound.
They resolve to **forty-nine distributions**. Before Phase 020 the workflows pinned
seven of them exactly and nothing recorded the other forty-two, so what entered an
environment depended on the day it was built.

Two consequences followed, and both were worse than the first.

`scripts/bootstrap.ps1` built `.venv` from those seven pins, which made a fresh
clone reproducible in name only. And `python -m tools.quality supply` audited a
requirements file synthesised from the pins, which `pip-audit` then **resolved
against a live index at audit time** — so the vulnerability report described a set
nobody had installed, and could differ between two runs on one commit.

---

## What is locked

| File | Covers | Produced by | Status |
|---|---|---|---|
| `pylock.dev.toml` | The `dev` extra and everything it resolves to | `pip lock` | Committed |
| `pylock.toml` | Runtime dependencies | `numpy`, `pandas`, `psutil` | Created in Phase 021; regenerable since Phase 024 |

Both names are fixed by PEP 751 rather than chosen: a lock is named `pylock.toml`
or `pylock.<name>.toml`, and `pip-audit --locked` globs exactly that at a project
path. Both live at the repository root, which is where every consumer looks.

### The runtime lock could not be regenerated until Phase 024

Stated plainly because it was a real defect rather than a design. This package was
written in Phase 020, when `project.dependencies` was empty and a contract test
kept it that way, so `development` was the only scope there could be. Phase 021
created `pylock.toml` and nothing here learned about it: `relock` and `upgrade`
both wrote `pylock.dev.toml` and nothing else, and — worse — `coverage_problems`
read `DEVELOPMENT` as a literal, so every `runtime_*` finding asked only whether
the runtime lock was sound *in itself* and none asked whether it held what had
been declared.

The consequence was invisible in exactly the way that matters. Adding `psutil` to
`project.dependencies` **and** to `[runtime] roots`, while leaving the lock
untouched, produced `lock: verdict passed`. A gate reporting success for something
that did not happen is the one failure this package exists to prevent.

Both halves are fixed. `relock` and `upgrade` regenerate both locks — holding the
workflow pins and the producer for the development scope only, because
`.github/workflows/` names nothing in `project.dependencies` — and a
`runtime_coverage` finding now asks the runtime lock the question the development
one was always asked.

### Why there was no runtime lock, and why there is one now

This section described the Phase 020 state — `project.dependencies` empty,
`[runtime] locked = false`, no `pylock.toml` — and **kept describing it for nine
phases after Phase 021 changed it**, contradicting the table above it in this
same file. Phase 029 repaired that; what follows is the record of why the
asymmetry existed and how it closed, because the mechanism is still load-bearing.

At Phase 020 a lock of an empty set would have restated a contract test by being
empty, and — decisively — `pip-audit --locked` **raises** on a lock recording no
packages rather than auditing it, so creating one would have broken the
vulnerability gate. The asymmetry was not left to memory:
`docs/engineering/lock-policy.toml` recorded `[runtime] locked = false` with its
reason, and the gate was written to fail with `LOCK_RUNTIME_UNLOCKED` the moment
`project.dependencies` became non-empty while no runtime lock existed.

**It fired exactly as designed.** Phase 021 could not introduce numpy and pandas
without producing `pylock.toml` in the same commit, and did not. `[runtime]
locked = true` today, the lock carries twenty-six distributions against nine
declared roots, and every claim it makes about itself is recomputed by the same
eleven checks the development lock faces. Phase 024 closed the remaining half of
the question — until then `coverage_problems` read `DEVELOPMENT` as a literal, so
the runtime lock was checked for internal soundness and never once asked whether
it contained what `pyproject.toml` declares.

---

## The declaration beside the lock

A pip-produced lock records only `lock-version`, `created-by` and `packages`. It
does **not** record the interpreter it is valid for, the index it came from, the
producer's version, or any dependency edges. A lock with no statement of its own
target agrees with whatever machine happens to read it.

So [`lock-policy.toml`](lock-policy.toml) is hand-written beside it and records the
producer, the target, the permitted digest algorithms, the roots the resolution was
performed from, the runtime-lock statement, and any owned gaps. Nothing generates
it; `relock` prints the lines a person must change and changes none of them,
because a declaration a tool rewrites is a mirror of that tool rather than a
statement anybody made.

---

## What the gate recomputes

```bash
python -m tools.quality lock
```

Offline, opening no socket. Every claim is derived from the lock's own contents
rather than taken on trust — the pattern
[ADR-0052](../adr/0052-wheel-availability-is-a-recorded-survey-whose-verdict-is-recomputed.md)
established for the wheel survey, applied to a second kind of record.

| Check | What is recomputed |
|---|---|
| Format | `lock-version` is a major this reader implements, and not a minor ahead of it |
| Producer | `created-by` is the declared tool, and a locked producer is the declared version |
| Target | The declared target matches [`runtime-contract.toml`](runtime-contract.toml), and the platform tag follows from the architecture under PEP 425 |
| Packages | Every name normalised under PEP 503 and unique; every entry versioned; no `vcs`, `directory` or `archive` source |
| Hashes | Every artefact carries a digest, in a permitted algorithm, of the right width and lowercase |
| Artefacts | Every artefact served over HTTPS, from the declared host, with no credential in the URL and no bare filesystem path |
| Compatibility | At least one recorded wheel filename's tags serve the pinned interpreter, and each filename's own name and version agree with the entry carrying it |
| Source | A package with no serving wheel is owned by a `[[gap]]` naming an undelivered phase |
| Declaration | The declared roots and `pyproject.toml` agree **in both directions**, and every declared tool is locked at a version clearing its bound |
| Registers | Every workflow pin and every mirrored hook revision equals the locked version |
| Runtime | Runtime dependencies and a runtime lock have appeared together |

The tag work is Phase 018's and is called rather than copied: the same
`serving_wheels` the wheel survey uses answers the compatibility question.

### What it does not check, and why

**The transitive closure.** pip records no dependency edges, so nothing offline can
prove that every locked package is reachable from a declared root. The roots are
compared in both directions, which catches a tool added to the project without
relocking and a tool removed from the project and left in the declaration. An
orphaned *transitive* package is closed by relocking, not by inspection. This is
the one place this arrangement is weaker than a lock from a resolver that records
edges, and it is stated rather than implied.

**The running producer's version.** The lock names its producer and not that
producer's version, so `[producer] version` cannot be recomputed from
`created-by`. What *is* checked is the other side of the same coin: pip is a real
transitive dependency of the toolchain, so it appears in the lock with a version,
and that version must equal the declared one — the lock installs the same producer
that wrote it. Whether the pip that *ran* was that version is observed by
`python -m tools.quality drift`, which classifies `pip.version` as material.

---

## Regenerating the lock

```bash
python -m tools.quality.lock relock
```

**This reaches the index.** It resolves the roots `pyproject.toml` declares — not
the ones the declaration records, so that the comparison between the two compares
two things rather than one — writes the result with LF endings, and then runs the
whole offline check against the candidate before keeping it.

Two versions are held rather than re-resolved, and the reason is the same in both
cases: a relock exists to record the *transitive* set nobody had pinned, not to
upgrade the direct toolchain somebody chose.

- **Every distribution the workflows pin**, so the seven measured tools do not move
  because a resolution ran.
- **The declared producer**, so an environment built from the lock does not hold a
  pip that never produced it.

A candidate that fails a check **about the lock itself** — a missing hash, an
untrusted artefact, an incompatible wheel — is refused: it is left at
`.globin/lock/rejected-lock.toml` and `pylock.dev.toml` is not touched. A candidate
that fails a check about the *repository* — a pin that has not been edited yet — is
kept, because otherwise the pins could never be brought into line with a lock that
would never exist. The exit code still reports everything found either way.

---

## Upgrading

### One package

```bash
python -m tools.quality.lock upgrade ruff
```

`pip lock` has no `--upgrade-package`; it re-resolves from bounds every time. So
this generates a constraints file from the committed lock — one `name==version` per
package, minus the ones named — and the diff becomes exactly what was asked for.

If the upgrade genuinely needs a neighbour to move too, pip reports a conflict
rather than dragging it along quietly. Add that neighbour to the argument list, or
run `relock`; either way the widening is a decision somebody made.

### The whole toolchain

Move the bound in `pyproject.toml`, or the pin in `.github/workflows/`, and then
relock. A tool held by a workflow pin does not move on its own.

### The procedure end to end

1. `python -m tools.quality.lock upgrade <name>` — or edit the bound and `relock`.
2. `python -m tools.quality lock` — it fails with `LOCK_REGISTER_DIVERGED` and
   **prints the exact `name==version` strings** the workflows must now carry.
3. Apply those to `.github/workflows/`, and the matching `rev:` to
   `.pre-commit-config.yaml` where a mirrored hook moved.
4. Update `[target] locked` in [`lock-policy.toml`](lock-policy.toml), and
   `[producer] version` if pip itself moved.
5. `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Recreate`.
6. `python -m tools.quality full`, then `python -m tools.quality.lock installed`,
   then `python -m tools.quality supply`.
7. Commit the lock, the declaration, the workflows and the hook configuration
   **together**. Any partial commit is red.

---

## Installing from the lock

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

`bootstrap` installs `pylock.dev.toml`, and pip derives hash checking from the lock
per requirement, so the install is verified without `--require-hashes` being
passed. This is what makes `python -m tools.quality.lock installed` a question
worth asking: an environment built from the seven pins would contain a resolution
performed on the day it ran, so the comparison would be red on a clean tree.

**An unreadable lock is a refusal, not a fall back to the pins.** A fallback is
used on exactly the day the lock is wrong. The recovery path is deliberate:

```bash
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -FromPins
```

It exists because `pip install -r pylock.toml` is labelled experimental upstream,
and the one command a person runs before they have a working tree needs a
hand-crank.

---

## Auditing

`python -m tools.quality supply` runs `pip-audit --locked` against the repository
root, which picks up every `pylock.*.toml` there — so the runtime lock Phase 021
adds is audited with no change to the tooling.

`--locked` resolves nothing. It reads names and versions straight from the lock,
which is the file `bootstrap` installs, so **the audited set and the installed set
are the same set**. `--strict` and `--format=json` stay, and `--fix` is still never
passed: choosing a version is the written review
[`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) describes, not something a
check does while running.

---

## What continuous integration still pins, and why

The exact `name==version` strings in `.github/workflows/` survive, as a derived
register rather than an authority. Three reasons:

- A pip-produced lock is valid for one interpreter and one platform, so it cannot
  serve the 3.12 entry in the `quality` matrix.
- The `mutation` and `shards` jobs install deliberate subsets; installing all
  forty-nine in each would change what those jobs measure and what they cost.
- `inventory.from_workflows` is the register both `inventory.drift()` and
  `bootstrap --from-pins` read, so emptying it has a blast radius well beyond
  locking.

The `lock` gate makes a pin that disagrees with the lock a failure and names the
replacement, so the two cannot drift apart.

The lock is **not** a fourth register inside `inventory.drift()`. That module
states about itself that it reads manifests and runs no resolver; a lock is
resolved, and putting one into it would make the claim false. The four-way
comparison lives in the lock gate, which imports the inventory rather than the
other way round.

---

## Deferred, with owners

| Question | Phase |
|---|---|
| The first runtime dependency, and the `pylock.toml` that must accompany it | 021 |
| Whether the `dev` extra becomes a PEP 735 dependency group | 021 |
| Widening the SBOM from the declared set to the locked transitive set | 021 |
| A second platform, which would need a second lock rather than an amendment | 023 |

**PEP 735 was considered and deferred on measurement rather than taste.** pip
accepts `--group` on `pip lock`, but its lock constructor never sets the
corresponding fields and unset fields are dropped, so a lock produced through a
dependency group is byte-identical to one produced from a requirements file. It
would touch a contract-tested invariant and three test modules for no observable
difference in the artefact. The argument for it — that a dependency group is not
installable as an extra of a published distribution — becomes visible when
`project.dependencies` is non-empty and something is published, which is Phase
021's.

---

## Related

- [ADR-0054](../adr/0054-the-toolchain-is-locked-with-pep-751-and-the-verdict-is-recomputed.md) — the decision
- [`lock-policy.toml`](lock-policy.toml) — the declaration the gate reads
- [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) — whether a dependency may be adopted
- [`RUNTIME_BASELINE.md`](RUNTIME_BASELINE.md) — the environment the lock is installed into
- [`WHEEL_AVAILABILITY.md`](WHEEL_AVAILABILITY.md) — the tag matcher this gate calls
- [`ENVIRONMENT_DRIFT.md`](ENVIRONMENT_DRIFT.md) — the other half of "is this environment right"
- [`QUALITY_GATES.md`](QUALITY_GATES.md) — where the gate is registered
- [`../research/phase_020_sources.md`](../research/phase_020_sources.md) — the evidence
