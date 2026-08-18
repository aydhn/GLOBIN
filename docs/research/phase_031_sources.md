# Phase 031 — Source Ledger

Every external claim Phase 031 relied on, where it was read, and what GLOBIN does
differently because of it. The rules this ledger follows are in
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

This phase has two halves — the degraded operation handling its title names, and the
secret materialization delivered as the fifteenth scope amendment. The first reaches
no external interface at all and is measured here; the second rests on one external
interface, the Windows Data Protection API, which is read rather than guessed. **Three
entries changed an implementation decision**, and that is said in bold where it
happened.

**No Binance documentation was consulted, and that omission is the decision rather
than an oversight.** This phase stores material it is given and has no way to obtain
any. Which key type a venue wants remains Phase 038's, what an environment *is*
remains Phase 035's, and signing — the only thing that would make a key type matter —
is Phases 033 and beyond. A storage layer that asked what Binance accepts would be
answering a question it must not have an opinion about.

**The DPAPI entries reverse a recorded decision, and were read for that purpose.**
[ADR-0074](../adr/0074-the-secret-store-is-the-windows-credential-manager-and-rotation-is-constructed.md)
declined a DPAPI-encrypted file on the store contract's own words. That refusal was
correct about the sentence it cited and is overturned deliberately rather than
forgotten; the reasoning is in ADR-0083 and the evidence is below.

---

### S-01 — The two DPAPI functions are exported by `Crypt32.dll`, not by `kernel32`

- **Canonical location:** Microsoft Learn, *CryptProtectData function (dpapi.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the vendor's own API reference.
- **Supports:** The requirements table gives header `dpapi.h`, library `Crypt32.lib`
  and DLL `Crypt32.dll`. The companion page for `CryptUnprotectData`
  (`https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata`)
  gives the same three.
- **Implication for GLOBIN:** `crypt32` is a **third** guarded Win32 library, joining
  `advapi32` and `kernel32` in `tests/architecture/test_credential_discipline.py`. It
  gets its own entry and its own sole permitted loader, for the reason that test
  already states: two adapters are absent-safe for different reasons, and folding
  them together would let one module quietly acquire the other's capability.

### S-02 — Both DPAPI calls allocate an output buffer the caller must free with `LocalFree`

- **Canonical location:** Microsoft Learn, *CryptUnprotectData function (dpapi.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** Of `pDataOut`, both pages state: "When you have finished using the
  **DATA_BLOB** structure, free its **pbData** member by calling the **LocalFree**
  function." The unprotect page adds that a non-`NULL` `ppszDataDescr` "must also be
  freed by using **LocalFree**".
- **Implication for GLOBIN:** **This changed a decision.** `LocalFree` is documented
  under `winbase.h` with library `Kernel32.lib` and DLL `Kernel32.dll` (S-03), and
  `kernel32` is already assigned to `globin.adapters.environment` as its sole
  permitted loader. Rather than widen that map to two modules — which is precisely
  the dilution its docstring argues against — the vault adapter is handed a narrow
  `local_free` callable by the module that already owns the library, the same way
  `WindowsCredentialStore` is handed its `library`. It acquires one named function,
  not a library. GLOBIN also passes `ppszDataDescr = NULL`, so the second free
  described above never arises.

### S-03 — `LocalFree` is a `kernel32` export, and it accepts a null handle

- **Canonical location:** Microsoft Learn, *LocalFree function (winbase.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-localfree`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** Header `winbase.h`, library `Kernel32.lib`, DLL `Kernel32.dll`. The
  signature is `HLOCAL LocalFree(HLOCAL hMem)`; the return value is `NULL` on success
  and "equal to a handle to the local memory object" on failure. Remarks: "If the
  *hMem* parameter is **NULL**, **LocalFree** ignores the parameter and returns
  **NULL**." Also: examining or modifying freed memory "may" corrupt the heap or
  raise `EXCEPTION_ACCESS_VIOLATION`.
- **Implication for GLOBIN:** The null tolerance is what lets the free live in an
  unguarded `finally` rather than behind an `if pointer is not None:`. A conditional
  free has a branch that only fires when an earlier call failed, which is the branch
  a test is least likely to reach and the leak most likely to survive; an
  unconditional one has no such branch. The read-after-free warning is why the
  decoded bytes are copied out with `ctypes.string_at` **before** the free rather
  than referenced after it — the same ordering `WindowsCredentialStore.resolve`
  already uses for `CredFree`.

### S-04 — `CryptUnprotectData` may succeed on corrupted input, and Microsoft asks for an application-level integrity check

- **Canonical location:** Microsoft Learn, *CryptUnprotectData function (dpapi.h)*,
  Remarks —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** "the specific error code returned when tampering is detected may vary
  depending on the nature of the corruption. The function may return
  ERROR_INVALID_DATA, ERROR_INVALID_PARAMETER, or in some cases may succeed with
  corrupted output. Applications should not rely on a specific error code to detect
  data tampering. For robust tamper detection, consider implementing additional
  integrity checks at the application level."
- **Implication for GLOBIN:** **This changed a decision.** The obvious design is to
  let DPAPI's own Message Authentication Code answer "was this file tampered with",
  and the vendor says in as many words that it will not. The vault envelope therefore
  carries a SHA-256 of its own, computed over the non-secret header and the
  ciphertext, and **verified before `CryptUnprotectData` is called** so corrupt input
  never reaches the cryptography. This is not the secret fingerprinting Phase 031
  forbids: DPAPI derives a fresh session key per call (S-09), so protecting one
  secret twice yields different ciphertext and therefore different digests. The
  digest identifies a *file*, not a *value*, and nothing can be reconstructed from it.

### S-05 — The DPAPI prompt-based flow has a removal date of February 2027

- **Canonical location:** Microsoft Learn, *CryptProtectData function (dpapi.h)*,
  `pPromptStruct` —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** "The prompt-based flow controlled by this parameter is deprecated and
  will be removed in **February 2027**. Passing **NULL** or a struct with
  `dwPromptFlags` set to 0 will use the non-interactive path for new operations.
  However, operations on data originally protected with the PromptStruct flow will
  fail." The same paragraph appears on the unprotect page.
- **Implication for GLOBIN:** GLOBIN passes `pPromptStruct = NULL`, so it is on the
  path that survives. `SECRET_STORE_CONTRACT.md` §7 already recorded that "a
  prompt-based flow has an expiry" and that "anything built on it would ship already
  ending"; the date is new and is now carried, because a limit with a date is
  checkable and a limit without one is a mood. Nothing GLOBIN writes will need
  migrating in February 2027, which is the point of recording it before it matters.

### S-06 — `CRYPTPROTECT_LOCAL_MACHINE` makes protected data readable by every account on the computer

- **Canonical location:** Microsoft Learn, *CryptProtectData function (dpapi.h)*,
  `dwFlags` —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** "When this flag is set, it associates the data encrypted with the
  current computer instead of with an individual user. **Any user on the computer on
  which CryptProtectData is called can use CryptUnprotectData to decrypt the data.**"
  Remarks repeat it.
- **Implication for GLOBIN:** The flag is not merely unused — **the constant is not
  defined anywhere in this repository**, so no later edit can pass it by reaching for
  a name that is already in scope. This is the same construction that keeps
  `CRED_PERSIST_ENTERPRISE` out of `adapters/secrets.py`, and an architecture test
  asserts the string appears nowhere under `src/`. The refusal matters more here than
  it would on a single-operator machine: GLOBIN is cloned onto several machines and
  run by several people under their own accounts, so a shared computer is a realistic
  case rather than a hypothetical one.

### S-07 — `CRYPTPROTECT_UI_FORBIDDEN` converts a UI requirement into a documented failure

- **Canonical location:** Microsoft Learn, *CryptProtectData function (dpapi.h)*,
  `dwFlags` —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** "This flag is used for remote situations where presenting a user
  interface (UI) is not an option. When this flag is set and a UI is specified for
  either the protect or unprotect operation, the operation fails and **GetLastError**
  returns the **ERROR_PASSWORD_RESTRICTION** code." The flag is documented on both
  the protect and the unprotect page.
- **Implication for GLOBIN:** Set on both calls, in addition to the null prompt
  struct of S-05. The two are not redundant: the null struct says *this operation
  does not ask for UI*, and the flag says *fail rather than show one*. GLOBIN runs
  unattended, and a call that blocks on a dialogue nobody is watching is
  indistinguishable from a hang — turning it into a named error code is what makes it
  reportable. `ERROR_PASSWORD_RESTRICTION` is mapped to a typed fault rather than
  left as an unknown status.

### S-08 — `CRYPTPROTECT_VERIFY_PROTECTION` reports that a blob should be re-protected

- **Canonical location:** Microsoft Learn, *CryptUnprotectData function (dpapi.h)*,
  `dwFlags` —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** "This flag verifies the protection of a protected BLOB. If the default
  protection level configured of the host is higher than the current protection level
  for the BLOB, the function returns **CRYPT_I_NEW_PROTECTION_REQUIRED** to advise
  the caller to again protect the plaintext contained in the BLOB."
- **Implication for GLOBIN:** Not used, and the omission is deliberate rather than an
  oversight. Acting on the advice means re-protecting — that is, writing the vault
  file again — during what the caller asked to be a *read*. A resolve that silently
  rewrites storage is the kind of surprise this repository refuses elsewhere, and the
  honest response to "your protection level is out of date" is an operator running
  `secrets rotate`. Recorded here so a later phase that wants it finds the flag and
  the argument together.

### S-09 — DPAPI binds to the user and the computer, and derives a session key per call

- **Canonical location:** Microsoft Learn, *CryptProtectData function (dpapi.h)*,
  Remarks —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata`
- **Accessed:** 2026-08-18
- **Authority:** Primary.
- **Supports:** "Typically, only a user with logon credentials that match those of the
  user who encrypted the data can decrypt the data. In addition, decryption usually
  can only be done on the computer where the data was encrypted. However, a user with
  a roaming profile can decrypt the data from another computer on the network." And:
  "The function creates a session key to perform the encryption. The session key is
  derived again when the data is to be decrypted."
- **Implication for GLOBIN:** Two things. First, "typically" and "usually" are the
  vendor's own hedges and are carried into the documentation as hedges — GLOBIN
  states that a vault **does not travel** between accounts or machines and that
  recovery is re-enrolment, never a copied file and never a plaintext backup. The
  roaming-profile exception is named rather than hidden, exactly as
  `SECRET_STORE_CONTRACT.md` §7 already names it for the Credential Manager. Second,
  the per-call session key is what makes the envelope digest of S-04 safe to publish.

### S-10 — `DATA_BLOB` is `CRYPTOAPI_BLOB`, two members in a fixed order

- **Canonical location:** Microsoft Learn, *CRYPT_INTEGER_BLOB structure* —
  `https://learn.microsoft.com/en-us/previous-versions/windows/desktop/legacy/aa381414(v=vs.85)`
- **Accessed:** 2026-08-18
- **Authority:** Primary — archived, and the current DPAPI pages link to it as the
  definition of the type they take.
- **Supports:** `typedef struct _CRYPTOAPI_BLOB { DWORD cbData; BYTE *pbData; }`, with
  `DATA_BLOB` among its aliases. Header `Wincrypt.h`. `cbData` is "the count, in
  bytes, of data"; `pbData` is "a pointer to the data buffer".
- **Implication for GLOBIN:** The `ctypes` structure declares the two fields in that
  order and a unit test pins the names, the order and the count — the same protection
  `_CREDENTIALW` already carries, and for the same measured reason: a wrong `ctypes`
  field width does not raise, it reads a neighbouring field, so a reordering during
  an edit would corrupt reads silently. `pbData` is declared `c_void_p` rather than
  `POINTER(c_byte)` because the latter is a *call*, and
  `tests/architecture/test_architecture_contract.py` holds every layer package to
  performing no work at import; it is cast where used.

---

## Deferred, and to where

| Question | Where |
|---|---|
| Which key type Binance wants, and what signing needs | Phases 033-038 |
| What an environment *is* | Phase 035 |
| Which credentials GLOBIN requires | Phase 038 |
| Which grants a key was actually issued with | Phase 039 |
| Whether the network is reachable, measured rather than declared | Phases 033+ |
| Whether GLOBIN adopts a GPU library | Phase 183 |
