# ADR-0074 — The secret store is the Windows Credential Manager, and rotation is constructed rather than inherited

## Status

Accepted — Phase 028.

**Date:** 2026-08-18

## Context

[`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md) states
plainly that it "decides no mechanism. It names no library, chooses no store, selects no
key type and creates no module." Phase 020 wrote it precisely so that this phase would
choose against measured limits rather than against a preference, and
[ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)
set the properties a store must have: outside the tree, owner-readable, protected by the
operating system, referred to by name.

Three candidates were put to the owner: the Windows Credential Manager reached through
`ctypes`, a DPAPI-encrypted file outside the tree, and the third-party `keyring` library.
**The owner chose the Credential Manager.**

## Decision

GLOBIN's local secret store is the **Windows Credential Manager**, reached through
`advapi32` in exactly one module, `globin.adapters.secrets`.

- **Credential type** `CRED_TYPE_GENERIC`, the one the operating system does not
  interpret.
- **Persistence scope** `CRED_PERSIST_LOCAL_MACHINE`.
- **Blob encoding** UTF-8.
- **One key builder**, `globin.domain.secrets.store_key`, folding case as its final step.
- **Rotation** is a four-step procedure in `globin.application.secrets.rotate`.

## Consequences

### The library choice added no dependency, and that was the deciding argument against `keyring`

`ctypes` is already in the I/O-capable list in
[`../architecture/dependency-rules.toml`](../architecture/dependency-rules.toml), so the
Credential Manager is reachable with nothing new declared. `keyring` would have required
a written six-question review, an entry in
[`../engineering/dependency-reviews.toml`](../engineering/dependency-reviews.toml), and
deterministic updates to both lock files — to wrap an API that is four calls wide.
`phase_020_sources.md` S-14 had already recorded what its Windows backend does, and it
is what this module does.

### DPAPI was declined on the contract's own words

A DPAPI-encrypted file satisfies "outside the tree" and "protected by the operating
system". It fails a sentence §7 of the contract already carries: "Using an
operating-system vault does not mean the application never holds the material. It means
the material is **not at rest in a file this repository can reach**." A DPAPI file is a
file, and something must know where it is. The vault has no such artefact.

### Two persistence scopes are declined by GLOBIN's policy, and neither by the platform

`phase_028_sources.md` S-07 measured all three scopes succeeding on this host, so
describing either refusal as a platform constraint would be false.

- `CRED_PERSIST_ENTERPRISE` is declined because S-08 of the Phase 020 ledger records it
  as visible "to logon sessions for this user on other computers", which widens a
  compromise past the single machine [ADR-0009](0009-windows-bat-launchers-as-entry-points.md)
  declares GLOBIN runs on.
- `CRED_PERSIST_SESSION` is declined because a credential that vanished at logoff would
  make an unattended restart fail in a way indistinguishable from corruption.

### The encoding was a defect, found by a test rather than by review

The obvious choice is UTF-16 little-endian, which is what most Windows credential tooling
writes. Under it the domain's ceiling and the platform's disagree by a factor of two for
ASCII: a 2560-character ASCII secret satisfies `SecretValue` and produces a 5120-byte
blob the platform refuses. **An API key is ASCII**, so that is the ordinary case rather
than an exotic one, and the domain would have been advertising a limit twice the real
one.

UTF-8 makes the two exact for every input. `WindowsCredentialStore.store` re-checks the
encoded length anyway, because the identity is a property of one constant and a constant
can be changed — and `test_the_adapter_still_refuses_an_oversized_encoded_form` forces
the encoding back to the one that caused the defect so the guard is exercised rather than
merely present.

### Rotation is constructed, and the platform forces one step the contract does not spell

§4 requires: write the new value, read it back and verify, and only then retire the
previous one — so that "a failure at any step leaves the previous secret resolvable".

A Windows credential write **replaces** (`phase_020_sources.md` S-10). By the time step 1
has run, the previous value is gone, so step 3 would be retiring something that no longer
exists. The procedure therefore has a step 0 the contract implies without stating: the
current value is copied to a second key first. `SecretSlot` is what makes that second key
exist, and it is a **bounded component of the key rather than a suffix on the name** —
otherwise a reference legitimately called `venue_key_previous` would address the previous
slot of `venue_key`, and a rotation would destroy an unrelated secret.

`RotationOutcome.previous_recoverable` reports whether working material can still be
obtained, because §4's guarantee is not "rotation succeeds" but "a failure leaves the
previous resolvable" — and a caller told only that rotation failed would not know which.

### The classification cannot be written from the documentation alone

`phase_028_sources.md` S-04 records that `CredWriteW` documents **no** status for a blob
that exceeds `CRED_MAX_CREDENTIAL_BLOB_SIZE`. S-05 records what this host actually
returns: **1783, `RPC_X_BAD_STUB_DATA`** — a name describing an RPC marshalling fault.
Code classifying against the documented list would file the one failure the ceiling
exists to cause under "unknown". `_fault_for` is therefore total over an unbounded input
and defaults to `BACKEND_REFUSED`, and the domain refuses an oversized value before the
platform is reached at all.

### The store lists nothing, and the emptiness is owned

`WindowsCredentialStore.inventory()` returns an empty tuple. Enumerating would mean
calling `CredEnumerateW` over every credential the account holds — including every one
written by unrelated software — and filtering by prefix. That reads other applications'
material to answer a question about GLOBIN. The set of references GLOBIN requires is
**declared rather than discovered**, and the declaration is Phase 029's; when it exists,
an inventory is that declaration resolved one reference at a time.

### What is not decided here

Which key type GLOBIN uses (Phases 029 and 038), which references a start-up requires
(Phase 029), how a credential is collected (Phase 029), and what an environment *is*
(Phase 035). `StoreBackedSecrets.required` is empty, and empty because GLOBIN holds no
credentials rather than by omission.

## Alternatives Considered

**A DPAPI-encrypted file.** Declined above, on §7's own wording.

**The `keyring` library.** Declined above, on dependency cost against a four-call API.

**Storing an encoded bundle in one credential rather than one value per reference.**
Declined on the ceiling: `phase_028_sources.md` S-11 measured an RSA-4096 private key in
PEM form at 3324 bytes, which already exceeds 2560 on its own. A bundle would have made
the limit arrive sooner and less predictably.

**Raising on an absent secret rather than returning a typed result.** Declined because
absence is an ordinary answer to the readiness question, and a start-up check must
receive it without unwinding. `require` is where a fault becomes a refusal, and the split
is by the caller's intent rather than the store's behaviour.

## Risks and Trade-offs

**The store separates accounts, not processes.** `phase_020_sources.md` S-09: anything
running as this user can read what this user stored. That is the honest scope of the
protection and the contract already says so; it is repeated here because a reader
reaching for "the operating system protects it" will not find that claim made anywhere.

**No claim of erasure is made, and none can be.** §7 records that CPython offers no
equivalent of `SecureZeroMemory` for a string. What is claimed is bounded lifetime and
no persistence, discharged by resolving in the narrowest scope that needs the value and
holding no cache.

**The leak gate covers eight surfaces and is a substring search.** It would not catch a
transformed or partially rendered value. `SecretValue`'s redaction of `__str__`,
`__repr__` and `__format__` is the mechanism; the gate is evidence that the mechanism
holds at each surface, not a proof that no other surface exists.

## References

- [ADR-0048](0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md) — the properties a store must have
- [ADR-0045](0045-a-platform-capability-is-a-recorded-state-never-a-pass.md) — a logon session with no credential set is a state
- [ADR-0073](0073-phase-028-widens-to-deliver-the-environment-capability-inventory.md) — the amendment this arrived under
- [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md) — the seven sections this implements
- [`../research/phase_020_sources.md`](../research/phase_020_sources.md) — S-08 to S-16, the platform limits
- [`../research/phase_028_sources.md`](../research/phase_028_sources.md) — S-04 to S-08 and S-11, measured on this host

## Supersedes

Nothing.

## Superseded By

Nothing.
