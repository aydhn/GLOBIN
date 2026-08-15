# Static Analysis

Which lint and type rules GLOBIN enforces, why each family was chosen, and how
to obtain an exception when a rule is wrong about a particular line.

All configuration lives in [`../../pyproject.toml`](../../pyproject.toml) and
nowhere else. This document explains the reasoning; it does not restate the
values, because a setting written in two places eventually has two values. Where
the gates run is [`QUALITY_GATES.md`](QUALITY_GATES.md).

---

## Ruff: lint and formatting

Ruff is both the linter and the formatter, which removes an entire class of
argument. When those are separate tools they disagree about line breaking, and
the disagreement is resolved by disabling rules until they stop fighting.

Rules are selected by family, against a stated priority order: **correctness,
import hygiene, unused code, obvious bug patterns, modern Python, and
maintainability.** Enabling several hundred rules because they exist produces
noise, and noise is how a team learns to ignore output.

### What each family is for

| Family | Buys |
|---|---|
| `E`, `W`, `F` | Syntax and obvious defects: undefined names, unused imports, unreachable code |
| `I`, `TID` | Deterministic import order; absolute imports only |
| `N`, `UP` | Naming conventions and modern syntax for the declared interpreter floor |
| `B`, `C4`, `SIM`, `RET`, `FURB` | Bug patterns and constructs with a clearer equivalent |
| `ARG`, `ERA` | Unused arguments and commented-out code — both are usually a leftover |
| `PTH` | `pathlib` over `os.path`, so path handling is uniform |
| `TC` | Imports needed only for typing, kept out of the runtime path |
| `RUF` | Ruff's own checks, including unused `noqa` directives |
| `S` | Shell and subprocess safety. Load-bearing: `tools/quality` runs subprocesses |
| `PGH` | Blanket `noqa` and `type: ignore` without a code |
| `PT` | Consistent pytest idiom across a suite several people will extend |
| `TRY`, `EM` | Exception antipatterns, and messages that read properly in a traceback |
| `DTZ` | Naive datetimes. A trading system that loses a timezone loses money |
| `A`, `SLF`, `INP` | Shadowed builtins, private access across objects, implicit namespace packages |
| `D` | Docstring conventions, under the **Google** style. Added in Phase 014, closing what Phase 004 parked |

### What is deliberately not enabled

Absences are decisions, and unrecorded decisions get reversed by whoever finds
them inconvenient.

| Not enabled | Reason |
|---|---|
| `ISC001` | Conflicts with the formatter; the two would fight on every run |
| `ANN` | Duplicates what mypy already enforces, more precisely |
| `PLR` magic-value rules | Noise against a codebase built almost entirely from named constants |

### Checking, fixing and formatting are separate commands

A verification command must never modify what it is verifying. Ruff is therefore
exposed as three distinct operations, and the two that write are named as such
in [`QUALITY_GATES.md`](QUALITY_GATES.md).

`--unsafe-fixes` is never passed by any command. An unsafe fix can change
behaviour, and a behaviour change should be made by someone who intended it.

---

## mypy: static typing

Every public function, method and module boundary is annotated
([`ENGINEERING_CONTRACT.md`](ENGINEERING_CONTRACT.md) invariant 8). mypy runs
over the package, the test suite and the tooling — tests included, because a
fixture returning the wrong type produces a test that passes for the wrong
reason.

### Why the flags are written out instead of `strict = true`

`--strict` is an alias whose membership mypy decides. It has grown between
releases and will grow again. Under the alias, upgrading mypy silently changes
what this repository's type contract *means*: a check appears or disappears with
no diff to read, no ADR, and no test failure.

So the flags are enumerated in `pyproject.toml`, read from `mypy --help` on the
version they were written against rather than from memory. A future mypy that
adds a flag to `--strict` will not acquire it here by accident; it will be
adopted deliberately.

A contract test asserts both that each flag is present and that `strict = true`
has not returned, so weakening the contract requires editing a test that says
why it should not be weakened.

### Beyond the alias

`warn_unreachable` and `warn_unused_configs` are enabled on top. So are several
error codes that are off by default, of which one matters most:

**`ignore-without-code`.** A bare `# type: ignore` silences every error on its
line, including errors written a year later that nobody has seen. Requiring the
code makes each suppression name the single thing it suppresses.

### Why `disallow_any_explicit` is not enabled

It would be satisfied by laundering. The contract tests parse TOML with
`tomllib`, whose return type is genuinely `dict[str, Any]`; banning the
annotation does not remove the `Any`, it removes the honest label for it and
replaces it with a cast asserting something untrue.

`Any` is controlled by the boundary-typing invariant and by review, not by a
flag that rewards concealment.

---

## Exceptions

Sometimes a rule is wrong about a specific line. That is expected. What is not
acceptable is an exception nobody can evaluate later.

### The procedure

1. **Establish the rule is wrong here**, not merely inconvenient. If the code
   can be changed to satisfy the rule without becoming worse, change the code.
2. **Suppress at the narrowest scope.** A `noqa` on one line beats a
   `per-file-ignores` entry, which beats removing a rule from `select`.
3. **Name the code.** `# noqa: S607`, never a bare `# noqa`. `PGH` and `RUF100`
   enforce this: a blanket suppression is an error, and so is one for a rule
   that is no longer firing.
4. **Write the reason next to it**, in terms of this project. "Linter is wrong"
   is not a reason; "`git` is resolved from `PATH` on purpose, and the argument
   list is a fixed literal" is.
5. **A repository-wide exemption needs an entry in `per-file-ignores` with a
   comment.** Each existing entry states its justification, and an entry added
   without one should be treated as a defect.

### Standing exceptions

| Exception | Where | Reason |
|---|---|---|
| `S101` (`assert`) | `tests/**` | `assert` is the assertion mechanism; pytest is never run under `-O` |
| `D103` (undocumented public function) | `tests/**` | A category error outside a library: a test function is public only in that nothing marks it private, nothing imports it, and its name is already a sentence. The *requirement* is dropped, not the practice — every other `D` rule still applies to the docstrings that exist |
| `S607` | `tests/support.py` | `git` is resolved from `PATH` on purpose; the argument list is a fixed literal |
| `S603` | `tools/quality/runner.py` | Arguments come from a frozen table of literals; `shell` is never enabled |

The list being short is the point. If it grows quickly, the rule set is wrong
and should be argued with, not worked around one line at a time.

It got shorter in Phase 005, which is the rarer direction and worth recording.
`globin.adapters.architecture` carried a `TRY004` exemption because every
malformed-contract path raised `ValueError` after an `isinstance` check, and the
rule asks for `TypeError`. The error taxonomy replaced those raises with
`ConfigurationError` ([ADR-0022](../adr/0022-error-taxonomy-rooted-in-one-type.md)),
which satisfies the rule outright, so the suppression was deleted rather than
reworded. An exemption that disappears because the underlying design improved is
the outcome this procedure is for; one that is reworded to survive a refactor
usually is not.

---

### Docstrings, and why the convention is declared rather than inferred

`convention = "google"` in `[tool.ruff.lint.pydocstyle]`. This repository has
written `Args:`, `Returns:` and `Raises:` since Phase 001; naming the style makes
that a rule instead of a habit.

Declaring it does more than pick a format. pydocstyle ships two pairs of rules in
mutual conflict — `D203` against `D211`, and `D212` against `D213` — and running
`D` without a convention leaves ruff warning about both on every invocation. The
convention resolves them by argument rather than by an arbitrary entry in an
ignore list, and it switches off the numpydoc section rules that would otherwise
fight the Google sections this repository already uses.

**One rule was reworded around rather than suppressed.** `D210` forbids
whitespace hugging the docstring text, and the formatter *inserts* a space when a
docstring opens with a quotation mark, to avoid producing four quotes in a row.
Five docstrings opened with a quoted phrase and hit that conflict. They were
reworded to lead with a word instead — the sentence is unchanged and the conflict
is gone. Adding `D210` to the ignore list would have been quicker and would have
switched off a rule that is right everywhere else.

## When a rule set change is a decision

Adding or removing a rule family changes what the repository permits, so it
belongs in the phase that decided it, with the reasoning recorded. Tightening
the configuration further — docstring rules, naming conventions — is Phase 013's
scope and is deliberately not done here.

The choices behind this configuration are recorded in
[ADR-0018](../adr/0018-quality-toolchain-and-explicit-strictness.md).
