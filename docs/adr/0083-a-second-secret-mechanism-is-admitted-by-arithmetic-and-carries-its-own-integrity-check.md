# ADR-0083 — A second secret mechanism is admitted by arithmetic and carries its own integrity check

## Status

Accepted — Phase 031. **Date:** 2026-08-18

## Context

[ADR-0074](0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md)
chose the Windows Credential Manager and declined a DPAPI-encrypted file, citing a
sentence [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md)
§7 already carried: *"the material is **not at rest in a file this repository can
reach**."* That refusal was correct about the sentence it cited.

The same phase then measured what the chosen store cannot do.
[`../research/phase_028_sources.md`](../research/phase_028_sources.md) S-11 records
`CRED_MAX_CREDENTIAL_BLOB_SIZE` at 2560 bytes and an RSA-4096 private key in PEM
form at **3324**. Binance's own documentation names Ed25519, RSA and a deprecated
HMAC as the key types it accepts, so a key GLOBIN will one day be handed may not
fit the only place GLOBIN has to put it. That is not a preference; it is a store
selected by this contract's own limits being unable to hold material the contract's
own future requires.

Phase 031 was directed to build the vault, and this record carries the mechanism
and the reversal. Every platform claim below is
[`../research/phase_031_sources.md`](../research/phase_031_sources.md)'s, read
during this phase rather than remembered.

## Decision

**1. A second mechanism exists, and ADR-0074's decision is narrowly reversed.**
Its §"DPAPI was declined on the contract's own words" and the matching
*Alternatives Considered* entry no longer hold, because §7's sentence has been
amended. **Everything else in ADR-0074 stands unchanged and still binding** — the
Credential Manager is still *the store*, `CRED_TYPE_GENERIC`,
`CRED_PERSIST_LOCAL_MACHINE`, the UTF-8 blob encoding, the one key builder and the
four-step rotation are all untouched. This is the shape
[ADR-0078](0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md)
used on ADR-0052 one phase ago, and ADR-0074's own status is not edited.

**2. The two mechanisms are disjoint by arithmetic rather than by policy.** The
vault admits what exceeds `MAX_SECRET_BYTES` and the Credential Manager admits what
does not, reading **the same constant**. No value belongs to both and none belongs
to neither, which is what stops a second mechanism becoming a second answer to one
question. `belongs_in_vault` takes the ceiling as an argument so the two cannot
drift apart, and takes **no `SecretKind`** — a private key that fits belongs in the
store, and routing by type would be storage taking an opinion about signing.

**3. There is no fallback edge, and its absence is enforced rather than promised.**
§3 forbids "a quiet fall back to somewhere less protected". `ProviderRoutedStore`
consults **exactly one** mechanism per reference and returns its fault;
`tests/unit/test_secret_environment.py` asserts the other receives zero calls,
because a fault can be right for the wrong reason and a call count cannot.

**4. The envelope carries its own integrity check, verified before the platform is
reached.** S-04 records that `CryptUnprotectData` may return either of two statuses
on corruption *"or in some cases may **succeed with corrupted output**"*, and that
applications "should not rely on a specific error code to detect data tampering".
Delegating the question to the platform would therefore be delegating it to
something the vendor says will not answer it. The envelope's SHA-256 covers the
magic, the schema version, the four identity fields and the ciphertext, and is
checked **before** `CryptUnprotectData` — so corrupted bytes never reach the
cryptography and a corrupted plaintext never exists as a Python string.

**This digest is not the secret fingerprinting §5 constrains.** DPAPI derives a
fresh session key per call (S-09), so protecting one value twice produces different
ciphertext and different digests. It is not a function of the plaintext and cannot
test a guess. **A digest over the plaintext was refused rather than overlooked**:
it would close the one gap this cannot — corruption arising inside DPAPI's own
decryption — by writing an offline-guessable oracle into a file.

**5. Machine scope is refused by construction.** `CRYPTPROTECT_LOCAL_MACHINE` is
defined in the adapter **precisely so that its absence from `PROTECT_FLAGS` can be
asserted**, the way `globin.domain.secrets` tests for a missing encoder rather than
trusting it. S-06 records the consequence of setting it: any user on the computer
can decrypt. That matters more here than on a single-operator host, because GLOBIN
is cloned onto several machines and run by several people under their own accounts.

**6. `CRYPTPROTECT_UI_FORBIDDEN` on both calls, and no prompt structure exists.**
S-05 records that the prompt-based flow "will be removed in **February 2027**" and
that passing null takes the non-interactive path. `pPromptStruct` is typed
`c_void_p` and always null, so **no such structure is declared anywhere in the
package** and there is no type for a later edit to populate. `ppszDataDescr` is
null too, which removes a second mandatory `LocalFree` rather than discharging it.

**7. `LocalFree` is borrowed as a callable, not as a library.** S-02 makes the free
mandatory and S-03 places it in `kernel32`, which
`tests/architecture/test_credential_discipline.py` already assigns to one module.
`windows_local_free()` hands the vault **one function**. Widening the guard map to
permit two loaders was declined: `kernel32` carries `CreateFileW`,
`CreateProcessW`, `VirtualAlloc` and the console API, so the grant would have been
wildly wider than the need, and the non-vacuity half of that test degrades over a
tuple of permitted modules.

**8. The native buffer is overwritten before it is released, and §7's blanket claim
is narrowed to say so.** That paragraph said no code in this repository can
establish that a value has been erased — true of a Python `str`, which is
immutable, may be interned and is moved by the allocator. A DPAPI output buffer is
a native allocation with a known address and length, so Microsoft's own
`SecureZeroMemory` guidance is followable here, uniquely. The contract now claims
the narrower, true thing rather than the broader, convenient one.

**9. The vault is a sibling directory, not a sixth `RuntimeArea`.** That
enumeration exists, in its own words, so a component asking for somewhere to write
"has to answer the question the enumeration poses: may this be deleted, and when."
All five answer *yes*. A vault answers *never — deleting it destroys material that
cannot be regenerated*. `RuntimeLayout` gains a `vault` segment, validated by the
same `segment_problems`; `RuntimeArea` keeps five members, so `prepare()` does not
create it, `boundary_outcome` does not count it and `FilesystemTreeProbe` does not
walk it.

**10. The publication sequence is extracted, not copied.** `AtomicDocumentWriter`
holds the temp-file-then-`fsync`-then-`replace` order and `AtomicStateStore`
delegates to it. The proof the extraction was behaviour-preserving is that
`tests/unit/test_runtime_state*.py` pass **untouched**, including the ones asserting
that a failed `fsync` leaves the previous document intact.

**11. `CRYPTPROTECT_VERIFY_PROTECTION` is declined and recorded as declined.** S-08
documents it as signalling through a *success* return plus `GetLastError`; acting
on the advice means re-protecting during a read, which turns `resolve()` into a
writer that would fail on a read-only filesystem; and `SecretResolution` has no
field for an advisory nothing consumes.

## Consequences

**What this costs.** A security-governed contract sentence changed, and a
recorded decision reversed. `RUNTIME_FILESYSTEM.md`'s absolute list loses one item
and gains a subsection explaining why. A reader tracing `LocalFree` now goes
through one indirection. And the vault directory is the first thing under
`%LOCALAPPDATA%\GLOBIN\` that is **not** disposable, which every sentence about
that tree now has to qualify.

**What is now prohibited that a contributor might reasonably want.** Storing
anything in the vault that fits the store. Reading the vault when the store is
unreachable. A `SecretKind` parameter on the admission rule. A plaintext export or
backup of a protected envelope — there is none, and recovery is re-enrolment.

**What enforcement exists.** `PROTECT_FLAGS & CRYPTPROTECT_LOCAL_MACHINE == 0`
asserted directly; the prompt and description arguments asserted null; the digest
gate asserted as **zero unprotect calls** on a tampered envelope; every platform
allocation compared against every address the injected deallocator received, on
every path including the failing ones; and `crypt32` held to one loader.

## Alternatives Considered

**A full supersession of ADR-0074.** Rejected as disproportionate. ADR-0074's
decision is that the Credential Manager is the store, and that is still true — the
vault holds only what the store structurally cannot. ADR-0078 established the
narrow-reversal shape one phase ago for exactly this situation.

**DPAPI-NG (`NCryptProtectSecret`), which takes a custom allocator and removes the
`kernel32` dependency entirely.** Genuinely tempting and declined on three counts:
it needs a protection-descriptor string, which means constructing a SID; the
allocator path is a `ctypes` callback whose failure mode is heap corruption rather
than an exception; and no research ledger in this repository has read it. Adopting
it would rest the phase's central mechanism on documentation nobody here has
consulted.

**A binary envelope format.** Rejected. A hand-rolled parser's field-offset bugs
are silent — the argument `_CREDENTIALW`'s own docstring makes about `ctypes` — and
the atomic writer opens in text mode, so a binary format would need a second write
path. JSON with base64 costs about a kilobyte and can be read by eye to confirm no
plaintext is present.

**Trusting DPAPI's own MAC for tamper detection.** Rejected on the vendor's own
words, quoted in decision 4. This is the one alternative that would have looked
correct in review and been wrong in fact.

**A `component_state()` method on both arms of all six absent-safe factories**, so
each module reports on itself rather than the survey classifying it. Declined for
cost, and the trade-off is recorded in `globin/adapters/degradation.py`'s docstring
rather than hidden: six modules and their tests would move to express one rule six
times. The tripwire is what makes the cheaper shape safe.

## Risks and Trade-offs

**The characteristic failure mode is that the admission rule stops being
arithmetic.** Decision 2 is what keeps this a *second mechanism* rather than a
*second store*, and it is one line. A later phase adding "and private keys always
go in the vault" would make the two overlap, at which point "where is this secret"
needs a lookup rather than a comparison. **The observable signal is a `SecretKind`
parameter appearing on `belongs_in_vault`.**

**The second is the gap the digest cannot close**, and it must be stated rather
than left for a reader to find: the digest covers the ciphertext, so corruption
arising *inside* DPAPI's own decryption is not caught. It is smaller than it
sounds — DPAPI's MAC does cover that, and the vendor's complaint is about error
*reporting* rather than about detection — but it is real, and closing it needs the
plaintext oracle decision 4 refuses.

**The third is that the vault is not disposable and lives beside four things that
are.** A non-developer operator clearing `%LOCALAPPDATA%` to free space loses key
material irrecoverably. The mitigation is documentation and a directory that is
created lazily, so its existence is itself evidence something was stored; there is
no technical guard, and there cannot be one.

**Confidence.** High on the platform facts — all ten were read from Microsoft's own
reference during this phase rather than remembered. High on the ordering argument
for the digest gate. Moderate on the vault's location: a sibling segment is the
right answer for the properties that matter, but it makes `RuntimeLayout` and
`RuntimeArea` describe overlapping-but-different sets, which a reader has to hold
in mind.

## References

- [ADR-0074](0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md) — the store; its §"DPAPI was declined on the contract's own words" is narrowly reversed here
- [ADR-0078](0078-the-second-lock-reader-is-the-reference-implementation-and-a-cache-is-not-a-source-of-trust.md) — the narrow-reversal shape this follows
- [ADR-0059](0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md) — the runtime tree; one item of its absolute list is narrowed, in `RUNTIME_FILESYSTEM.md` rather than in that immutable record
- [ADR-0082](0082-phase-031-widens-to-deliver-the-user-scoped-secret-vault.md) — the amendment that admitted this work
- [`../research/phase_031_sources.md`](../research/phase_031_sources.md) — S-01 to S-10
- [`../security/SECRET_VAULT.md`](../security/SECRET_VAULT.md) — what an operator needs to know

## Supersedes

Nothing.

## Superseded By

Nothing yet.
