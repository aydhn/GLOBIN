# The Secret Store

What GLOBIN's local secret store is, what it guarantees, and what it refuses.

[`SECRET_STORE_CONTRACT.md`](SECRET_STORE_CONTRACT.md) specifies the store's
obligations and decides no mechanism. **This document records the mechanism that
was chosen and how it satisfies each obligation.** Where this and the contract
appear to disagree, the contract wins, under the authority order in
[`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md).

Reasoning:
[ADR-0074](../adr/0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md).
Every platform claim is measured, in
[`../research/phase_020_sources.md`](../research/phase_020_sources.md) S-08 to
S-16 and [`../research/phase_028_sources.md`](../research/phase_028_sources.md)
S-04 to S-08 and S-11.

> **GLOBIN holds no credentials.** The store exists; the set of secrets a
> start-up requires is empty, and empty because nothing has needed one rather
> than by omission. Collecting and validating a credential is Phase 029's.

---

## The mechanism

The **Windows Credential Manager**, reached through `advapi32` in exactly one
module.

| | |
|---|---|
| Credential type | `CRED_TYPE_GENERIC` — the one the operating system does not interpret |
| Persistence | `CRED_PERSIST_LOCAL_MACHINE` |
| Blob encoding | UTF-8 |
| Maximum value | 2560 bytes, `CRED_MAX_CREDENTIAL_BLOB_SIZE` |
| Key format | `globin:<environment>:<kind>:<name>:<slot>`, lowercase |
| New dependency | **None.** `ctypes` is already permitted. |

`CRED_PERSIST_ENTERPRISE` and `CRED_PERSIST_SESSION` are declined by **GLOBIN's
policy, not by the platform** — all three scopes work on this host. Enterprise
persistence makes a credential visible on that user's *other computers*, which
widens a compromise past the one machine GLOBIN runs on; session persistence
would make an unattended restart fail in a way indistinguishable from corruption.

---

## A reference is not a value

Two types, and the distinction is enforced by the type system rather than by
care.

A **`SecretReference`** names a secret. It is ordinary data: printable,
loggable, serialisable, comparable, and safe in a configuration file, an error
message or a manifest. It carries no material and never has.

A **`SecretValue`** is what resolving one returns. Four obligations, each
structural:

- `__str__`, `__repr__` **and `__format__`** all yield the redaction marker.
  The third matters more than it looks: `object.__format__` with a non-empty
  spec does not route through `__str__`, so a type overriding only the first two
  would *raise* on `f"{value:>40}"` — and a redaction that raises is one somebody
  removes.
- It is **not a dataclass**, and has no `__dict__`. `vars()`, `asdict()` and
  anything written against either find nothing to walk.
- It has **no encoder**. `SERIALIZATION_POLICY.md` is exact or refused; for a
  secret the answer is refused.
- It is **unhashable**, so it cannot become a dictionary key or a set member.

Comparison is constant-time and reveals nothing about content.

---

## One key builder

Exactly one total, pure function maps a reference to the key it is stored under.
Nothing else composes one anywhere.

**Case is folded, and that is correctness rather than tidiness.** A Windows
target name is case-insensitive, and the collision is *silent*: a credential
written under one spelling is returned for another with no error and no warning.
A builder that did not fold would produce keys that look distinct, pass a test
that writes and reads through the same spelling, and collapse the environment
isolation the store exists to provide — only once two environments differed by
case.

Length is not a constraint. The platform permits 32767 characters, so the key is
verbose and unambiguous on purpose.

---

## Environment isolation

A credential minted for one environment never resolves in another. The
environment is part of the key, so a mismatch **cannot resolve** — the isolation
is a property of the key builder rather than a check somebody has to remember to
write.

Absence, an unreachable store, a wrong kind, and a logon session with no
credential set are each an **explicit, named fault**. None is a silent `None`,
an empty string, or a placeholder.

---

## Rotation, and what survives a failure

The contract requires: write the new value, read it back and verify, and only
then retire the previous one — so that *a failure at any step leaves the previous
secret resolvable*.

A Windows credential write **replaces**. There is no compare-and-swap, no version
token and no exchange, so by the time the new value is written the old one would
already be gone. The procedure therefore has a step the contract implies without
stating:

0. **Copy the current value to the `previous` slot.**
1. Write the new value to the `current` slot.
2. Read it back and compare it against what was written.
3. Only then delete the previous copy.

A failure at any step leaves working material obtainable, and the outcome reports
**whether it does** rather than only that the rotation failed — that is the
question an operator is about to ask.

The slot is a bounded component of the key rather than a suffix on the name, so a
reference legitimately called `venue_key_previous` cannot collide with the
previous slot of `venue_key`.

---

## What is never displayed

There is **no verb that returns a secret** to a terminal, a file, the clipboard
or a log: no `show`, `reveal`, `print`, `dump`, `export`, `cat`; no `--secret=`
or any other option that would place material on a command line, where it is
visible in the process table and recorded in shell history; and no verbosity
level that widens any command into one.

A contract test holds that list against the module names, the command table and
the function surface of the four secret modules.

---

## The leak gate

A synthetic canary is proven absent from eight surfaces. The contract named four
of them as uncovered when it was written; all four are covered now:

| Surface | How |
|---|---|
| Log records, through every sink | Redaction at construction, plus the value type's own rendering |
| Standard output and standard error | Every printing route exercised |
| An exception's `str()` and `args` | A refusal built from the reference and the fault, never the value |
| A traceback, including chained causes and notes | Rendered from a real nested frame |
| The JUnit report, coverage output, `.globin/` uploads | `tools/quality/evidence/redaction.py` |
| The process command line | Read from a **real child process**, so it is what the operating system recorded |

**Redaction is not itself a store.** Nothing retains a value in order to redact
it later; the central control is the type, not an accumulating register.

---

## What the platform does not guarantee

These are limits, written as limits, because "the operating system protects it"
reads as a guarantee nobody made.

- **It separates accounts, not processes.** Anything running as this user can
  read what this user stored.
- **Some logon sessions have no credential set at all.** A network logon does
  not have one. That is a recorded state, never a crash.
- **Memory is not erasable.** CPython offers no equivalent of `SecureZeroMemory`
  for a string: its objects are immutable, may be interned, and are copied and
  moved by the interpreter. GLOBIN claims **bounded lifetime and no
  persistence**, and never erasure — discharged by resolving in the narrowest
  scope that needs a value and holding no cache.

---

## The ceiling, and what does not fit

2560 bytes, measured: 2560 succeeds and 2561 fails. The failure arrives as
**1783 `RPC_X_BAD_STUB_DATA`**, a status `CredWriteW` documents nowhere — so the
store refuses an oversized value *before* the platform is reached, and an
operator gets a named reason rather than an RPC marshalling error.

Measured against real keys of the types the venue documents:

| Encoded form | Bytes | Fits |
|---|---:|:--:|
| Ed25519 private, PKCS#8 PEM | 122 | yes |
| RSA-2048 private, PKCS#8 PEM | 1732 | yes |
| **RSA-4096 private, PKCS#8 PEM** | **3324** | **no** |
| RSA-4096 private, PKCS#8 DER | 2348 | yes, by 212 bytes |

**An RSA-4096 key in the form a person actually handles does not fit.** That is a
constraint on key choice, discovered here rather than by a failed write in a
later phase. It is also a measured reason to prefer Ed25519, which Binance
already recommends and which leaves the ceiling irrelevant. **No key type is
chosen here** — that is Phases 029 and 038.

---

## What this does not cover

| Question | Phase |
|---|---|
| Whether a venue agrees a key carries the permissions declared for it | 039 |
| Which references a start-up requires | 038 |
| Which key type is used against which surface | 038 |
| What an environment *is*, and how production, testnet and demo differ | 035, delivered — [`../engineering/ENVIRONMENT_CLASSES.md`](../engineering/ENVIRONMENT_CLASSES.md) |

---

## Related

- [`SECRET_STORE_CONTRACT.md`](SECRET_STORE_CONTRACT.md) — the obligations this satisfies
- [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md) — the rules a secret is handled under
- [ADR-0074](../adr/0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) — the mechanism decision, and the alternatives declined
- [ADR-0048](../adr/0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — where a secret may live
- [`../research/phase_028_sources.md`](../research/phase_028_sources.md) — every platform claim, measured
