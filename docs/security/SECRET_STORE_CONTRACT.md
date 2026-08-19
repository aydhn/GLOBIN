# Secret Store Contract

The interface a stored secret is reached through, what the Windows protection
beneath it does and does not guarantee, and what a later phase must prove rather
than assert.

**This restates neither
[ADR-0048](../adr/0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)
nor [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md).** Those own where a secret may
live and where it may not; this owns how one is reached and what holds it up.
Where this and either of them appear to disagree, they win, under the authority
order in [`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md).

**It decides no mechanism.** It names no library, chooses no store, selects no key
type and creates no module. Every section states the phase it binds.

> **Phase 028 has since chosen one**, and the choice is recorded in
> [`SECRET_STORE.md`](SECRET_STORE.md) and
> [ADR-0074](../adr/0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md)
> rather than here. This document keeps its original shape deliberately: it states
> what any store must satisfy, and remains the thing a replacement mechanism would
> be judged against.

---

## Why this exists

ADR-0048 chose the store's properties as capabilities rather than mechanisms —
outside the tree, owner-readable, protected by the operating system, referred to by
name — and gave its reason: *"so that Phase 028 can satisfy them with whatever
Windows actually offers. If none can, this record is superseded rather than quietly
ignored."*

That set a test and did not run it. Running it means reading what Windows offers,
and discovering the limits inside which the later phases must choose. This document
runs it. The measurements are recorded in
[`../research/phase_020_sources.md`](../research/phase_020_sources.md) entries S-08
to S-14, and the consequences are the seven sections below.

Two of those measurements would otherwise be discovered late and expensively: the
credential blob has a documented ceiling of **2560 bytes**, and a write **replaces**
with no compare-and-swap. The first decides whether a given key can be stored at
all; the second decides that rotation has to be constructed rather than inherited.

---

## 1. A reference is not a value

*Binds Phase 028.*

Two distinct types, and the distinction is enforced by the type system rather than
by care.

A **reference** names a secret. It is ordinary data: printable, loggable,
serialisable, comparable, and safe to put in a configuration file, an error message
or a manifest. It carries no secret material and never has.

A **value** is what resolving a reference returns. It is subject to four
obligations:

- Its `__str__` and `__repr__` yield the redaction marker
  `globin.domain.observability.REDACTED` — reached by reference, never spelled a
  second time. A second literal would be an uncompared copy, which
  [`../engineering/SOURCE_OF_TRUTH.md`](../engineering/SOURCE_OF_TRUTH.md) calls
  drift.
- It is not a plain field a generic dump helper walks. Whatever mechanism Phase 028
  chooses, the failure mode to design out is a serialiser meeting the object and
  doing the obvious thing.
- It has **no encoder**. [`../SERIALIZATION_POLICY.md`](../SERIALIZATION_POLICY.md)
  is exact or refused; for a secret value the answer is refused, in the way
  `MonotonicReading` already has no wire form.
- Comparison neither echoes the material nor branches on it in a way a message
  could reveal.

Ordinary configuration carries a reference. It does not carry a value, and a
validator that meets secret-shaped material in a configuration file refuses it
rather than accepting and redacting it later.

**The type and module names are Phase 028's**, and it chose `SecretReference` and
`SecretValue` in `globin.domain.secrets`. The absent-capability rule that had
constrained them is now narrower rather than lifted: `credential`, `password`,
`token`, `keyring` and `apikey` remain forbidden as module names because credential
*handling* is still absent and still Phase 029's, while `secret` is permitted
because the store exists and `README.md` says so.

---

## 2. One builder for a store key

*Binds Phases 026, 027 and 035.*

Exactly one total, pure function maps a secret's identity to the key it is stored
under. Nothing else composes one, anywhere. Identical inputs give an identical key;
an input the function cannot classify is **refused**, never defaulted.

Three properties come from the platform rather than from preference (S-08):

- The key identifies GLOBIN. Microsoft asks that a generic credential's target name
  identify the service using it and suggests prefixing it with the implementing
  company's name.
- Length is not a constraint. The name may be up to 32767 characters, so a
  structured, verbose, unambiguous key is what the platform expects. Compression is
  not a virtue here.
- **The name is case-insensitive, so case is normalised or the isolation in §3 is
  not real.** Two keys differing only in case are one credential. A builder that
  did not normalise would produce keys that look distinct and collide.

A fourth property is procedural: a target name **cannot be edited after creation**.
Changing the scheme is therefore a delete-and-recreate migration, not a rename,
which is why the scheme is fixed by this contract before anything writes to a
store.

---

## 3. Environment isolation fails closed

*Binds Phases 029, 030 and 035.*

A credential minted for one environment never resolves in another. Resolution
compares the environment requested against the environment encoded in the key, and
a mismatch is a **typed refusal** under the taxonomy in
[`../adr/0022-error-taxonomy-rooted-in-one-type.md`](../adr/0022-error-taxonomy-rooted-in-one-type.md)
— not a warning, not a fallback to a default, not an empty value the caller may
mistake for absence.

The same applies to a secret that is absent, to a store that cannot be reached, and
to material whose kind is not what was asked for. Each is an explicit error. None
is a silent `None`, an empty string or a placeholder.

An error may name the logical secret, name the backend fault, and name the command
that would remediate it. It may not carry the material, nor a prefix of it, nor
anything from which it could be reconstructed.

**What an environment *is* was Phase 035's, and is now answered** in [`../engineering/ENVIRONMENT_CLASSES.md`](../engineering/ENVIRONMENT_CLASSES.md). This fixes only that the
comparison happens and that a mismatch refuses.

A related platform fact belongs here rather than in §7, because it is about
availability rather than protection: some logon sessions have no credential set at
all (S-09). That is a state to be recorded and refused in the manner
[ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md)
requires — never a crash, and never a quiet fall back to somewhere less protected.

---

## 4. Rotation replaces without losing

*Binds Phases 028 and 029.*

Rotation is a first-class operation, and it has an order:

1. Write the new value.
2. Read it back and verify it is the value that was written.
3. Only then retire the previous one.

A failure at any step leaves the previous secret resolvable. That ordering is the
whole of the guarantee.

**The platform supplies none of this.** A write creates or replaces, and the only
flag offered *preserves* an existing value rather than comparing one — there is no
conditional write, no version token and no exchange (S-10). So the procedure is
constructed here rather than inherited, and a bare overwrite is lossy.

An audit trail may record the logical reference, the operation, the outcome, the
time and the environment. It may not record the old material, the new material, or
any part of either. A rollback path that logs what it rolled back from has defeated
the store.

---

## 5. The command surface is defined by what is absent

*Binds Phases 029 and 030.*

No verb returns a secret to a terminal, a file, the clipboard or a log. There is no
`show`, `reveal`, `print`, `dump`, `export`, `cat` or `copy`; no `--secret=` or any
other option that would place material on a command line, where it is visible in
the process table and recorded in shell history; and no verbosity level that widens
any command into one.

Permitted operations: set (interactive entry only), verify presence (returning a
boolean), list (names, environments, kinds and existence only), delete, rotate, a
backend health check, and a per-mechanism capability report.

**The seventh was added by Phase 031 and is not a widening of what may be seen.**
`health` answers whether *a* backend can be reached; `doctor` answers which of the
several mechanisms this host has and what each can do. It reads no operator secret,
emits no value, and where it round-trips anything at all it generates its own
sentinel and removes it in a `finally`. A verb that reported on a mechanism by
reading something stored in it would be `list` with a misleading name.

An inventory listing may show a non-reversible fingerprint. If it does, the digest
must not permit reconstruction and the full value must not be retained anywhere to
compute it against.

Entry rules are [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md)'s and are not
restated. One addition belongs here because it is newly evidenced (S-13): the
standard library's echo-free prompt documents a fallback that **does** echo,
signalled by a warning. This contract requires that warning to **abort collection**
rather than merely be printed. The suite already turns warnings into errors, so it
is an error under test; making it an error at runtime is what matters, because
runtime is where the operator is and where the echoed value would reach a
scrollback buffer.

---

## 6. What a leak gate must prove

*Binds Phases 028, 029 and 030.*

A synthetic canary — of the shape
[`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) prescribes, and never anything
shaped like a real credential, because ADR-0048's prohibition admits no exception —
must be proven absent from each of:

- log records, through every sink
- standard output and standard error
- an exception's `str()` and its `args`
- a traceback, including chained causes and any attached notes
- the JUnit XML report
- the coverage report and its raw database
- anything under `.globin/` that continuous integration uploads
- the process command line and environment, as observed from outside the process

Two of these are already covered and the rest are not, and saying which is the
point. `tools/quality/evidence/redaction.py` scans published artefacts, which
covers the JUnit report, the coverage output and the `.globin/` uploads.
`globin.domain.observability` redacts during construction, which covers log
records. Exceptions, tracebacks, standard streams and the process's own command
line are **not** covered today by anything.

Redaction must not become its own hazard. A mechanism that retained every secret it
had ever seen, in order to redact it later, would be a store nobody declared. The
central control is the secret type itself, not an accumulating register of values.

---

## 7. What the platform does not guarantee

*Binds Phases 028 and 030.*

Every claim here is from primary documentation, cited in the ledger. They are
written as limits because the alternative — "the operating system protects it" —
reads as a guarantee nobody made.

| Limit | What it means |
|---|---|
| It separates accounts, not processes | Protection is scoped to the logon session's credential set. Anything running as that user can read what that user stored (S-09) |
| "Typically" and "usually" are the vendor's own words | Data protection binds to the user and the computer with documented exceptions; a roaming profile is one of them (S-11) |
| Enterprise persistence roams | A credential written with the roaming scope is visible to that user's sessions on other computers (S-08) |
| Machine scope is refused | Associating protection with the computer rather than the user makes it readable by **every** account on that computer (S-11) |
| A prompt-based flow has an expiry | It is deprecated with a removal date — **February 2027** — so anything built on it would ship already ending (S-11; the date is `../research/phase_031_sources.md` S-05) |
| Its own tamper check is not reportable | Unprotection may return either of two statuses on corruption **or succeed with corrupted output**, and the vendor says not to rely on a code to detect tampering. An application-level check is required, and runs first (S-04) |
| The blob has a ceiling | `CRED_MAX_CREDENTIAL_BLOB_SIZE`, 2560 bytes. Phase 028 paid that measurement: 2560 succeeds, 2561 fails with an undocumented status, and an RSA-4096 key in PEM form does **not** fit (`../research/phase_028_sources.md` S-05, S-11) |
| Memory is not erasable | See below |

**On zeroisation, plainly.** Microsoft's guidance recommends overwriting a secret
buffer when finished with it (S-12). CPython offers no equivalent for a string: its
objects are immutable, may be interned, and are copied and moved by the interpreter
and its allocator, so no code in this repository can establish that a value has been
erased from process memory.

GLOBIN therefore claims **bounded lifetime and no persistence**, and never erasure.
Microsoft's actual principle — collect late, discard early — is discharged by
resolving a secret in the narrowest scope that needs it and holding no long-lived
cache, not by a call that would look like erasure without being it.

**Phase 031 narrowed that claim, because the broader one was not true of
everything.** A *native* buffer — one a platform call allocated, whose address and
length GLOBIN knows — can be overwritten before it is released, and the DPAPI vault
does exactly that before calling `LocalFree` (`../research/phase_031_sources.md`
S-02, S-03). The paragraph above remains exactly right about a Python `str`, which
is what a caller ends up holding. So the honest statement is in two parts: **the
native buffer is overwritten; the Python string decoded from it is not, and cannot
be.** Claiming the stronger absence where the weaker one is achievable would have
been the easier sentence and the wrong one.

Using an operating-system vault does not mean the application never holds the
material. It means the material is never at rest **unprotected**, and never at rest
in a file **inside this repository's tree**.

**Phase 031 narrowed this sentence, and the narrowing is an amendment rather than a
clarification.** As first written it said "not at rest in a file this repository can
reach", and [ADR-0074](../adr/0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md)
declined a DPAPI-protected file on those words. The sentence was doing two jobs at
once: keeping material out of the checkout, which is unchanged and absolute; and
forbidding *any* file at all, which was a consequence of the wording rather than a
decision anybody took against a measurement. Phase 028 then paid the measurement —
the ceiling above is 2560 bytes and an RSA-4096 key in PEM form is 3324 — so the
store this contract's own limits selected **cannot hold material this contract's own
future requires**. A protected file is how that material is held, and
[ADR-0083](../adr/0083-a-second-secret-mechanism-is-admitted-by-arithmetic-and-carries-its-own-integrity-check.md)
records the reversal.

**The rule that replaces it is narrower and checkable.** Material may be at rest in
a file only when every one of these holds, and a file failing any of them is a
defect rather than a variation:

1. It is outside the repository tree, and outside every area
   [`../engineering/RUNTIME_FILESYSTEM.md`](../engineering/RUNTIME_FILESYSTEM.md)
   declares disposable.
2. Its contents are protected by the operating system under the **current user**,
   so that a copy of the bytes is worthless on another account or another machine.
3. It carries only material the chosen store structurally cannot — the ceiling
   above is the admission test, and a value that fits belongs in the store.
4. **Nothing reads it as a fallback** when the store is unreachable. §3 requires a
   typed refusal, and a quiet fall back to somewhere less protected is precisely
   what that section forbids.
5. It carries its own integrity check, verified **before** the platform is asked to
   decrypt — because `CryptUnprotectData` documents that its own check may "succeed
   with corrupted output" (`../research/phase_031_sources.md` S-04).

---

## What this does not cover

| Question | Phase |
|---|---|
| Where configuration files live, and what profiles exist | 026, delivered — [`../engineering/CONFIGURATION_LAYOUT.md`](../engineering/CONFIGURATION_LAYOUT.md) |
| Which configuration sources are consulted, and in what order | 027, delivered — [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md) |
| Whether a venue agrees a key carries the permissions declared for it | 039 |
| Which preflight checks run before a long-running process starts | 030, delivered — [`../engineering/PREFLIGHT_SUITE.md`](../engineering/PREFLIGHT_SUITE.md) |
| What an environment is, and how production, testnet and demo differ | 035, delivered — [`../engineering/ENVIRONMENT_CLASSES.md`](../engineering/ENVIRONMENT_CLASSES.md) |

Which permissions a Binance key carries is not in that table. It is a question of
fact about a venue, governed by
[ADR-0006](../adr/0006-product-and-environment-capability-matrix.md) and already
routed by [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md). What this phase
established is only that the grants have real names to be narrow about, and that
one interface accepts a single key type (S-15, S-16) — so a store that could not
carry that material would foreclose it.

---

## What can and cannot be enforced

Most of this cannot be checked by a gate today, because none of what it constrains
exists yet. ADR-0048 made the same admission about itself and named the failure
mode: a later phase reads the rules, agrees with them, and implements something
subtly outside them, because nothing fails.

Two things do the enforcing instead, and neither is decoration.

**Time.** The deferral table above is compared against `ROADMAP.md`. The day any of
those phases is marked complete, the contract test goes red and this document must
be reconciled in the same commit.

**Absence.** No command in `tools/quality/commands.py` and no module under
`src/globin/` may carry one of the verbs §5 forbids. That passes vacuously today
and goes red the first time somebody adds a `reveal`.

Everything else is review, which is weaker than a test and is what is available
before the thing exists. A gate invented here to look thorough would be worse than
none, because it would read as coverage.

---

## What a change touching this contract must satisfy

- The reference type and the value type are still distinct, and the value type
  still has no encoder and no plain string form.
- Store keys still come from one function, still normalise case, and still refuse
  what they cannot classify.
- An environment mismatch is still a typed refusal.
- Rotation still verifies before it retires, and still writes no material anywhere.
- No command has gained a way to display a secret, including through a verbosity
  flag.
- The leak-gate list has not shrunk, and any surface added to the system has been
  added to it.
- No claim of erasure, and no claim about the platform that its own documentation
  does not make.

---

## Related

- [ADR-0048](../adr/0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — where a secret may live, and why redaction happens at construction
- [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md) — the rules a secret is handled under
- [`VULNERABILITY_RESPONSE.md`](VULNERABILITY_RESPONSE.md) — the credential-exposure lane, and why deleting a committed secret is not enough
- [`../LOGGING_POLICY.md`](../LOGGING_POLICY.md) — log redaction, which this does not restate
- [`../SERIALIZATION_POLICY.md`](../SERIALIZATION_POLICY.md) — exact or refused
- [`../research/phase_020_sources.md`](../research/phase_020_sources.md) — every platform claim above, with its source
