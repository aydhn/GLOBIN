# The secret vault

Where GLOBIN keeps key material too large for the Windows Credential Manager, what
protects it, and — the part that matters most to an operator — what it does **not**
promise.

Delivered by Phase 031. The decisions are
[ADR-0083](../adr/0083-a-second-secret-mechanism-is-admitted-by-arithmetic-and-carries-its-own-integrity-check.md);
the obligations every mechanism must satisfy are
[`SECRET_STORE_CONTRACT.md`](SECRET_STORE_CONTRACT.md); the chosen store is
[`SECRET_STORE.md`](SECRET_STORE.md).

---

## 1. Why there are two mechanisms

The Credential Manager has a ceiling. `CRED_MAX_CREDENTIAL_BLOB_SIZE` is 2560
bytes, and Phase 028 measured what that excludes: an RSA-4096 private key in PEM
form is 3324 bytes and does not fit
([`../research/phase_028_sources.md`](../research/phase_028_sources.md) S-11).
Binance's own documentation names Ed25519, RSA and a deprecated HMAC as the key
types it accepts, so a key GLOBIN may one day be handed can be larger than the only
place GLOBIN had to put it.

**The two are disjoint by arithmetic, not by policy.**

| Material | Mechanism |
|---|---|
| At or below 2560 bytes | Windows Credential Manager |
| Above 2560 bytes | The vault |

Both read the same constant, so no value belongs to both and none belongs to
neither. An Ed25519 private key in PKCS#8 PEM form is 122 bytes and lives in the
**store**; nothing routes by key *type*, because which algorithm a key is for is a
signing concern and signing is Phases 033 onwards.

**There is no fallback between them.** A reference names one mechanism and that
mechanism's answer is the answer. `SECRET_STORE_CONTRACT.md` §3 forbids "a quiet
fall back to somewhere less protected", and the absence is asserted as a call count
rather than promised in prose.

---

## 2. What protects it

Windows DPAPI, through `CryptProtectData` and `CryptUnprotectData`, under **your
own account**. GLOBIN invents no cryptography: there is no AES layer, no
key-derivation function, no master password and no hard-coded key anywhere in this
repository.

Two flags matter, and both are refusals.

- **`CRYPTPROTECT_LOCAL_MACHINE` is never passed.** With it set, *any* account on
  the computer can decrypt what you stored. The constant is defined in the adapter
  **so that its absence can be asserted by a test** — an absence does not appear in
  a diff.
- **`CRYPTPROTECT_UI_FORBIDDEN` is always passed.** GLOBIN runs unattended, and a
  call that blocks on a dialogue nobody is watching is indistinguishable from a
  hang. With the flag, the platform returns an error instead.

The prompt-based flow Microsoft is removing in **February 2027** is not used: GLOBIN
passes a null prompt structure, which is the path that survives. No such structure
is declared anywhere in the package, so no later edit can populate one.

---

## 3. What is on disk

One JSON file per secret, under `%LOCALAPPDATA%\GLOBIN\vault\`. You can open one
and confirm for yourself that no plaintext is in it.

| Field | What it is |
|---|---|
| `magic` | Identifies the file as a GLOBIN envelope |
| `schema_version` | Refused rather than read if it announces a later shape |
| `environment`, `kind`, `name`, `slot` | Which secret this is — ordinary data, safe to write down |
| `protected` | The ciphertext, base64-encoded |
| `digest` | A SHA-256 over the header and the ciphertext |

**The envelope carries its own integrity check because the platform's cannot be
relied on.** Microsoft states plainly that `CryptUnprotectData` may return either
of two error codes on corruption *or may succeed with corrupted output*, and that
applications must not rely on a code to detect tampering
([`../research/phase_031_sources.md`](../research/phase_031_sources.md) S-04). So
GLOBIN checks its own digest **before** calling the platform: corrupt bytes never
reach the cryptography, and a corrupted plaintext never exists.

**The digest is not a fingerprint of your secret.** DPAPI derives a fresh key per
call, so protecting the same value twice produces different ciphertext and a
different digest. It identifies a *file*, not a *value*, and nothing can be
recovered or guessed from it. A digest over the plaintext was deliberately refused:
it would have let anyone holding the file test candidate secrets offline at their
own speed.

**It detects corruption, not tampering.** It is unkeyed and stored beside what it
covers, so somebody who can write the file can recompute it. Claiming otherwise
would be the appearance of protection without the substance.

---

## 4. What this does **not** promise

Read this section before relying on the vault.

**A vault does not travel.** DPAPI binds protection to your Windows account and
your computer. Copying the folder to another machine, or to another account on the
same machine, produces files that cannot be decrypted. Microsoft's own wording is
"typically" and "usually" — a roaming profile is a documented exception — and
GLOBIN repeats the hedge rather than rounding it up to a guarantee.

**There is no backup and no export.** No command writes a secret anywhere you could
read it. Moving to a new machine or a new account means **enrolling the credentials
again**, from whatever you originally got them from. That is a deliberate cost: an
export path is the single most likely way a key leaves the machine.

**The vault is the one part of GLOBIN's runtime tree that is not disposable.**
`state/`, `cache/`, `run/`, `tmp/` and `logs/` may all be deleted at any time and
GLOBIN will rebuild them. `vault/` may not. Deleting it destroys material that
cannot be regenerated. It is created by the first write rather than at start-up, so
its existence is itself a signal that something is stored there.

**Erasure is not claimed for the whole path.** The native buffer the platform fills
in is overwritten before it is released — that much is real and testable. The
Python string decoded from it is **not** erased and cannot be: CPython strings are
immutable, may be interned, and are moved by the interpreter and its allocator.
GLOBIN claims bounded lifetime and no persistence, never erasure.

**Storing a key type is not authenticating with it.** That the vault can hold
Ed25519, RSA or HMAC material does **not** mean GLOBIN can sign a request, reach a
venue or place an order. Signing is Phase 038; the product surfaces are Phases
033 onwards. This document is about storage and nothing else.

---

## 5. Where the boundary is

| Question | Where |
|---|---|
| What every mechanism must satisfy | [`SECRET_STORE_CONTRACT.md`](SECRET_STORE_CONTRACT.md) |
| The chosen store, and why | [`SECRET_STORE.md`](SECRET_STORE.md) |
| How a credential is collected and rotated | [`CREDENTIAL_FLOW.md`](CREDENTIAL_FLOW.md) |
| Where a secret may live at all | [`SECURITY_BASELINE.md`](SECURITY_BASELINE.md) §2 |
| What the runtime tree holds | [`../engineering/RUNTIME_FILESYSTEM.md`](../engineering/RUNTIME_FILESYSTEM.md) |
| Which credentials GLOBIN requires | Phase 038 |
| Which grants a key was issued with | Phase 039 |
| Signing a request | Phase 038 |
| Operator-controlled credential recovery and onboarding | Phase 292 |

---

## Related

- [ADR-0083](../adr/0083-a-second-secret-mechanism-is-admitted-by-arithmetic-and-carries-its-own-integrity-check.md) — the decisions, and the refusals inside them
- [ADR-0074](../adr/0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) — the store, and the decline Phase 031 narrowly reversed
- [`../research/phase_031_sources.md`](../research/phase_031_sources.md) — every platform claim above, with where it was read
