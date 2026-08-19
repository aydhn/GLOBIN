# Configuration Layout

Where GLOBIN's configuration documents live, what they are called, and what a
profile is.

[`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) owns the *model*: what a
setting is, how layers fold, and which values are refused. This owns the *layout*.
The split is ADR-0027's, and it is what let the model exist for nineteen phases
without anybody having to decide where a file goes.

---

## Configuration is a third kind of thing

GLOBIN already has two trees and neither is right for this.

| Tree | Holds | Property |
|---|---|---|
| `.globin/` | evidence about **this repository** | Git-ignored, regenerable |
| `%LOCALAPPDATA%\GLOBIN\` | state about **this machine** | every area safe to delete |
| `config/` | **authored operator intent** | committed, reviewable, irreplaceable |

Configuration is hand-written and is the one thing in the system whose loss cannot
be recovered by re-running anything. `.globin/` is wrong because a fresh clone would
lose it. The user-local tree is wrong for a sharper reason: every area of it is
documented *safe to delete*, and an authored document there would be the first
un-deletable thing in a tree whose entire design rests on disposability — which is
[ADR-0059](../adr/0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md)'s
own named characteristic failure arriving early.

There is a second reason, and it is the one that decides it: a document that will
one day select **live trading** must be visible in a diff.

---

## The layout

```text
config/
├── globin.toml              base; applies whatever profile is selected
├── profiles/
│   ├── paper.toml
│   ├── demo.toml
│   ├── testnet.toml
│   └── live.toml
└── local/                   Git-ignored: the operator's own, never committed
```

`config/local/` is ignored as **defence in depth, not as a licence**.
[`../security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) says a secret
never arrives through configuration at all, and Phase 028 stores a *reference*. The
rule is here anyway, before the directory exists, because what Git records once it
records permanently.

The ignore pattern is **anchored** — `/config/local/` — because a bare `local/`
matches at every depth, which is how Phase 018 silently lost `tools/quality/wheels/`
to an unanchored `wheels/`.

---

## Nothing searches

Given a layout and a profile, the set of candidate documents is a **pure function**
of the two. There is no upward walk, no fallback chain, and no
first-one-that-exists-wins.

That is not minimalism. Each of those is a *precedence* decision, and precedence is
Phase 027's question. `adapters/configuration.py` has said since Phase 007 that the
path is given rather than guessed, and warns that searching here would settle Phase
026's decisions by accident; this layout keeps that sentence true by **computing
spellings** rather than looking anything up.

`ConfigLayout.documents_for` returns a **mapping**, never a sequence. A tuple has an
order and a reader would read that order as precedence. The return type is where the
boundary is held.

---

## A profile names a document, not an environment

Phase 035 decided what an environment *is* — see [`ENVIRONMENT_CLASSES.md`](ENVIRONMENT_CLASSES.md); Phase 036 decides which product and
environment pairs are usable. A Phase 026 implementation that made `testnet` mean
something would answer their question six phases early.

The boundary is held by a mechanism that already exists rather than by a new rule:
`as_config` refuses every key outside `known_keys()`, and not one of those keys can
say anything about a venue, a URL or a product. **A profile document is structurally
incapable of asserting what an environment is**, even if somebody tried.

**The domain bounds the shape; the composition root names the instances.** Three of
the four names — `demo`, `testnet`, `live` — are venue vocabulary, and
`tests/architecture/test_identifier_discipline.py` refuses venue vocabulary as a
live constant anywhere under `globin.domain`. So `domain/config_layout.py` states
what a profile name may look like and `composition.PROFILES` supplies the four; that
is `identifiers.py`'s kinds-not-instances discipline applied again.

An unrecognised name is **refused**, never matched to a nearest neighbour and never
defaulted. Case and surrounding whitespace are forgiven, because both are accidents
of a launcher argument's transport. Uppercase inside the name is not: a profile
becomes a filename, and Windows compares filenames case-insensitively, so `Paper`
and `paper` would name one document while comparing unequal everywhere else.

`DEFAULT_PROFILE` is `paper`, and it must never be `live` — ADR-0006's "never
downgraded to production" read in the direction nobody writes down.

---

## The four documents set nothing

That is the deliverable rather than a shortfall. GLOBIN does not trade, so there is
no setting that differs between the four for a reason anybody could defend today.
Writing one in would invent a difference to justify the files, and would encode a
belief about how they differ in a document nobody would think to look in.

`CONFIGURATION_POLICY.md` already describes exactly this shape — *"a source with
nothing to say still returns a layer"* — and
`tests/contract/test_configuration_layout_contract.py` folds all five documents over
the declared defaults and asserts the result **is** the declared defaults. The day
one of them sets a value, that test fails and somebody has to say why.

---

## What may never go in this tree

No API key, no secret, no token, no credential of any kind, and no reference to one.
`config/` is committed and this repository is public; treat every file in it as a
public document, because it is one.

---

## TOML, and one argument that is not "it is already here"

`tomllib` is **read-only**. GLOBIN can never write a configuration file back, so an
operator's comments, ordering and formatting cannot be destroyed by the program. A
configuration format the program can rewrite is one that eventually loses somebody's
comment explaining why a number is what it is.

---

## A limitation, stated rather than discovered

`find_project_root` walks up from the working directory, so an installed `globin`
run from an arbitrary directory finds no root and therefore no configuration — and
runs on declared defaults. In the intended deployment the launchers Phase 289 owns
set the working directory inside the checkout.

**Phase 030 did not repair this, and gave it an escape and a witness instead.** The
escape is `--config PATH`, which is resolved to an absolute path, so an operator who
needs a specific document from an arbitrary directory names one and gets it — and
gets a refusal rather than silence if it is not there. The witness is
[`CONFIGURATION_EVIDENCE.md`](CONFIGURATION_EVIDENCE.md): `config explain` names every
layer that was consulted, including the ones that contributed nothing, so "no
configuration was found" is now something a run *says* rather than something a
reader has to infer from values that look like defaults.

**Implicit discovery is still working-directory dependent**, and no amount of
reporting changes that. Repairing it would mean choosing a search rule — an installed
package's location, an environment variable naming a root, a registry entry — and
every one of those is a precedence decision of the kind this document exists to keep
out of the layout.

---

## What this does not cover

| Question | Phase |
|---|---|
| Which documents are consulted, in what order, and whether a missing one is fatal | 027, delivered — [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) |
| How a profile name reaches the process | 027, delivered — [ADR-0071](../adr/0071-configuration-precedence-is-declared-and-an-environment-variable-is-a-derived-name.md) |
| Where a secret is stored and how it is supplied | 028, delivered — [`../security/SECRET_STORE.md`](../security/SECRET_STORE.md) |
| What an environment is, and how production, testnet and demo differ | 035, delivered — [`ENVIRONMENT_CLASSES.md`](ENVIRONMENT_CLASSES.md) |
| Which product and environment pairs are usable | 036 |

---

## Related documents

- [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) — the settings register.
- [`RUNTIME_FILESYSTEM.md`](RUNTIME_FILESYSTEM.md) — the tree this one is not.
- [ADR-0069](../adr/0069-configuration-is-derived-rather-than-searched-and-a-profile-names-a-document.md)
  — the decision.
