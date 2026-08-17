# Phase 028 — Source Ledger

Every external behaviour this phase depends on, with the primary source that
established it. The rules this ledger obeys — which sources count as primary, what each
entry must record, and when a claim must be re-verified — are in
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

This phase has two halves and the ledger reflects both: the local secret store the
roadmap assigns to Phase 028, and the environment capability inventory delivered
alongside it. Entries marked **Probe** were measured on this host rather than read; each
records what was run and what it answered.

Three entries changed an implementation decision rather than confirming one — S-02,
S-06 and S-09 — and each says so where it did.

---

### S-01 — `IsWow64Process2` reports the process machine as `UNKNOWN` precisely when the process is *not* emulated

- **Canonical location:** Microsoft Learn, *IsWow64Process2 function (wow64apiset.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the platform vendor's reference for the function.
- **Supports:** Of `pProcessMachine`: "A pointer to the variable that, on success,
  receives an `IMAGE_FILE_MACHINE_*` value. The value will be
  **IMAGE_FILE_MACHINE_UNKNOWN** if the target process is not a WOW64 process;
  otherwise, it will identify the type of WoW process." Of `pNativeMachine`: it
  "receives a possible `IMAGE_FILE_MACHINE_*` value identifying the native architecture
  of host system." Minimum supported client is **Windows 10, version 1709**; minimum
  supported server is Windows Server 2016, version 1709. The library is `Kernel32.lib`.
- **Implication for GLOBIN:** The naming is a trap and the mapping must be written
  against the sentence rather than against the constant's name.
  `IMAGE_FILE_MACHINE_UNKNOWN` is `0`, and a reader mapping it onto a
  `CapabilityStatus.UNKNOWN` would report every healthy native machine as unmeasured —
  inverting the meaning of the one value that appears on an ordinary host. GLOBIN
  therefore reads a process machine of `0` as **not emulated**, and derives the process
  architecture from the native machine in that case.
  The version floor matters too: `runtime-contract.toml` declares `minimum_release =
  "10"` with no build component, so a supported host may predate 1709 and lack this
  function entirely. Presence is probed rather than assumed — see S-03.

### S-02 — `GetNativeSystemInfo` misreports the native architecture on ARM64, and Microsoft says to use `IsWow64Process2` instead

- **Canonical location:** Microsoft Learn, *GetNativeSystemInfo function (sysinfoapi.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getnativesysteminfo`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the platform vendor's reference for the function.
- **Supports:** "Retrieves information about the current system to an application
  running under WOW64. If the function is called from a 64-bit application, it is
  equivalent to the `GetSystemInfo` function. **If the function is called from an x86 or
  x64 application running on a 64-bit system that does not have an Intel64 or x64
  processor (such as ARM64), it will return information as if the system is x86 only if
  x86 emulation is supported (or x64 if x64 emulation is also supported).**" And in its
  Remarks: "To determine if a Win32-based application is running under WOW64 (or if a
  64-bit system does not have an Intel64 or x64 processor), call the `IsWow64Process2`
  function." Minimum supported client is Windows XP.
- **Implication for GLOBIN:** **This changed a decision.** The obvious design — and the
  one this phase's plan carried — was to fall back to `GetNativeSystemInfo` when
  `IsWow64Process2` is unavailable. That fallback is unsound for the *native* question:
  on an ARM64 host running an x64 interpreter it answers x64, which is wrong in exactly
  the case native-architecture detection exists to detect, and wrong in a way no caller
  could notice. The vendor's own remark routes that question to the other function.
  So the fallback is kept for the *process* architecture, where the function is
  equivalent to `GetSystemInfo` and correct, and the native architecture is recorded as
  **`UNKNOWN`** when `IsWow64Process2` is absent. ADR-0045's rule is what makes that the
  cheap answer rather than an embarrassing one: not knowing is a state, and a confident
  wrong answer is not.

### S-03 — Probe: this host has `IsWow64Process2`, runs natively, and is AMD64 by both routes

- **Canonical location:** The development host, read directly through
  `ctypes.WinDLL("kernel32")`. Documentation for the functions consulted:
  `https://learn.microsoft.com/en-us/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the machine reporting its own state, in the manner of
  `phase_017_sources.md` S-03 and S-06.
- **Supports:** `hasattr(kernel32, "IsWow64Process2")` is `True` and the call returns
  non-zero with `GetLastError()` of `0`. It reports `pProcessMachine = 0`
  (`IMAGE_FILE_MACHINE_UNKNOWN`) and `pNativeMachine = 34404` (`0x8664`,
  `IMAGE_FILE_MACHINE_AMD64`). `GetNativeSystemInfo` independently reports
  `wProcessorArchitecture = 9` (`PROCESSOR_ARCHITECTURE_AMD64`) with 16 logical
  processors. `IsWow64Process` — the older function — is also present.
  `ctypes.sizeof(ctypes.c_void_p) * 8` is `64` and `sys.platform` is `win32`.
- **Implication for GLOBIN:** The development host is a native AMD64 machine running a
  64-bit interpreter with no emulation, which is the case the contract already declares
  in `runtime-contract.toml`. It is also the case that produces `process_machine = 0`,
  so S-01's trap is not hypothetical here — it is the value this host returns on every
  run, and a wrong mapping would have shown as a permanent amber rather than as a rare
  edge case. The two routes agreeing is what licenses using `GetNativeSystemInfo` for
  the process question in S-02's fallback.

### S-04 — `CredWriteW` documents no error for an oversized credential blob

- **Canonical location:** Microsoft Learn, *CredWriteW function (wincred.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the platform vendor's reference for the function.
- **Supports:** The documented status codes are `ERROR_NO_SUCH_LOGON_SESSION`,
  `ERROR_INVALID_PARAMETER`, `ERROR_INVALID_FLAGS`, `ERROR_BAD_USERNAME`,
  `ERROR_NOT_FOUND`, and four smart-card errors. **None of them describes a
  `CredentialBlobSize` that exceeds the limit.** `ERROR_INVALID_PARAMETER` is documented
  for a different cause entirely: "Certain fields cannot be changed in an existing
  credential. This error is returned if a field does not match the value in a protected
  field of the existing credential." The remarks confirm S-10 of the Phase 020 ledger:
  "If a credential with the specified **TargetName** and **Type** exists, the new
  specified credential replaces the existing one."
- **Implication for GLOBIN:** The ceiling that `CREDENTIALW` documents (S-08 of the
  Phase 020 ledger, `CRED_MAX_CREDENTIAL_BLOB_SIZE`, 2560 bytes) has no documented
  failure code attached to it, so the behaviour on breach had to be measured rather than
  looked up. See S-05. This is why the store checks the length **before** the call
  rather than classifying the error afterwards: a limit enforced by the caller is a
  typed refusal naming the reference, and one discovered from an undocumented status
  code is a guess about what the platform meant.

### S-05 — Probe: the ceiling is exactly 2560 bytes, and one byte over returns an undocumented `RPC_X_BAD_STUB_DATA`

- **Canonical location:** The development host, read directly through
  `ctypes.WinDLL("advapi32")`. Documentation for the limit under test:
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the machine reporting its own state.
  `SECRET_STORE_CONTRACT.md` §7 names this as "a measurement Phase 028 owes on the
  real host".
- **Supports:** Writing a generic credential with a blob of exactly
  `CRED_MAX_CREDENTIAL_BLOB_SIZE` (2560) bytes succeeds, returning `TRUE` with
  `GetLastError()` of `0`. Writing **2561** bytes fails, and writing 3072 bytes fails,
  both with `GetLastError()` of **1783**. `ctypes.WinError(1783).strerror` resolves that
  to "the stub received bad data" — `RPC_X_BAD_STUB_DATA`. The value is not
  `ERROR_INVALID_PARAMETER` (87), not `ERROR_BAD_LENGTH` (24) and not
  `ERROR_INSUFFICIENT_BUFFER` (122).
- **Implication for GLOBIN:** The documented ceiling is real and exact — 2560 succeeds,
  2561 does not — so the constant may be relied on as a bound. But the *failure* is
  reported through a status code the function's own documentation never mentions and
  whose name describes an RPC marshalling fault, so code that classified errors by
  matching the documented list would file the one failure the ceiling exists to cause
  under "unknown". GLOBIN refuses an oversized value in the domain, before the adapter
  is reached, and the adapter maps 1783 to a bounded reason rather than re-deriving
  intent from it. Whether a real Binance key fits is not in doubt at this size; the
  ceiling constrains what *else* may ever be put in one credential, which is why the
  store holds one value per reference rather than an encoded bundle.

  **It also decided the blob encoding, and a test found that.** The ceiling is in
  *bytes*, so which bytes depends on how GLOBIN encodes the material — a choice the
  platform leaves open, because a credential blob is opaque to it. The obvious
  encoding is UTF-16 little-endian, which is what most Windows credential tooling
  writes; under it an ASCII secret encodes to twice its length, so a value of exactly
  2560 characters satisfies the domain's bound and produces a 5120-byte blob the
  platform refuses. An API key is ASCII, so that is the ordinary case. GLOBIN encodes
  **UTF-8**, which makes the domain's advertised limit and the platform's enforced one
  the same number for every input; verified against the real store, 2560 ASCII
  characters now write and read back byte-identically.

### S-06 — Probe: a generic credential's target name is case-insensitive in practice, and a second write replaces

- **Canonical location:** The development host, read directly through
  `ctypes.WinDLL("advapi32")`. The documented claim under test:
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the machine reporting its own state, confirming the
  documented claim recorded as S-08 in the Phase 020 ledger.
- **Supports:** A credential written under a mixed-case target name was read back
  successfully under the same name **upper-cased**, returning a byte-identical blob.
  Writing a second, different value under the original name returned `TRUE`, and a
  subsequent read returned the second value — with no flag passed and no conflict
  reported. Reading a name that was never written fails with `GetLastError()` of
  **1168**, `ERROR_NOT_FOUND`. This logon session does have a credential set:
  no call returned `ERROR_NO_SUCH_LOGON_SESSION` (1312).
- **Implication for GLOBIN:** **This changed a decision.** Case-insensitivity was
  documented and therefore already a requirement on the key builder; measuring it
  established something the documentation does not say, which is that the collision is
  *silent* — the second name neither fails nor warns, it simply resolves to the first
  credential. A builder that did not normalise would therefore produce an environment
  isolation that looks implemented, passes a naive test that writes and reads through the
  same spelling, and fails only when two environments differ by case. `store_key` folds
  case as its final step, and a property test asserts that two references differing only
  in case produce the same key rather than asserting they produce different ones.
  The replacing write confirms S-10 of the Phase 020 ledger against the running system:
  rotation gets no atomicity from the platform, so the write-verify-retire ordering in
  `SECRET_STORE_CONTRACT.md` §4 is the entire guarantee.

### S-07 — Probe: this host accepts all three persistence scopes, so refusing two is GLOBIN's policy rather than the platform's

- **Canonical location:** The development host, read directly through
  `ctypes.WinDLL("advapi32")`. Documentation for the persistence scopes:
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the machine reporting its own state.
- **Supports:** Generic credentials written with `CRED_PERSIST_SESSION` (1),
  `CRED_PERSIST_LOCAL_MACHINE` (2) and `CRED_PERSIST_ENTERPRISE` (3) each returned
  `TRUE` with `GetLastError()` of `0`. All probe credentials were deleted afterwards
  with `CredDeleteW`, each returning `TRUE`, and a subsequent read of every written
  target confirmed none remained.
- **Implication for GLOBIN:** The store uses `CRED_PERSIST_LOCAL_MACHINE` and refuses
  `CRED_PERSIST_ENTERPRISE`, and this entry is what stops that being written as though
  the platform imposed it. The enterprise scope works here; it is declined because S-08
  of the Phase 020 ledger records that it makes the credential "visible to logon sessions
  for this user on other computers", which widens the blast radius of a compromise
  beyond the single machine ADR-0009 declares. Saying "the platform refuses it" would be
  false, and `SECRET_STORE_CONTRACT.md` §7 already insists that a limit be written as a
  limit rather than as a guarantee nobody made. The session scope is declined for the
  opposite reason: a credential that vanishes at logoff would make an unattended restart
  fail in a way that looks like corruption.

### S-08 — Probe: the probe credentials were removed, and the removal was verified rather than assumed

- **Canonical location:** The development host, read directly through
  `ctypes.WinDLL("advapi32")`. Documentation for the persistence scopes:
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the machine reporting its own state.
- **Supports:** Five target names were written during measurement, all prefixed
  `GLOBIN:phase028:probe:`. Each was deleted with `CredDeleteW`, every call returning
  `TRUE` with `GetLastError()` of `0`, and a read of each name afterwards returned the
  residue list `[]`. Every payload written was plain ASCII describing itself as a
  measurement; no value with any credential shape was created at any point.
- **Implication for GLOBIN:** Recorded because a probe that writes to a real,
  user-visible operating-system store owes an account of what it left behind, and
  "I deleted them" is a claim rather than evidence. The verification pass is the
  evidence. It is also the pattern the store's own rotation must follow — write, read
  back, then act on what the read said — which is why the probe was written that way.

### S-09 — `shutil.which` uses `PATHEXT`, and consults the current directory unless the mode says otherwise

- **Canonical location:** Python documentation, `shutil.which` —
  `https://docs.python.org/3/library/shutil.html`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the standard library's own documentation.
- **Supports:** "Also on Windows, the `PATHEXT` environment variable is used to resolve
  commands that may not already include an extension." And: "On Windows, the current
  directory is prepended to the *path* if *mode* does not include `os.X_OK`. When the
  *mode* does include `os.X_OK`, the Windows API `NeedCurrentDirectoryForExePathW` will
  be consulted to determine if the current directory should be prepended to *path*. To
  avoid consulting the current working directory for executables: set the environment
  variable `NoDefaultCurrentDirectoryInExePath`." Changed in 3.12: "`PATHEXT` is used now
  even when *cmd* includes a directory component or ends with an extension that is in
  `PATHEXT`; and filenames that have no extension can now be found."
- **Implication for GLOBIN:** **This changed a decision.** The brief asked that
  current-directory resolution not be trusted for a security-sensitive decision, and the
  obvious reading was that `which` never looks there. It does — unconditionally when the
  mode omits `os.X_OK`. Measured on this host, the default `mode` is `1`, which is
  `os.F_OK | os.X_OK` and therefore *does* include `os.X_OK`, so the default already
  routes through `NeedCurrentDirectoryForExePathW` rather than prepending blindly. The
  default is relied on deliberately and the mode is passed explicitly anyway, so that a
  later edit cannot silently widen it. More importantly, the toolchain result is
  advisory: every toolchain capability is **optional**, so a discovery that found the
  wrong executable degrades a report rather than authorising anything.

### S-10 — Probe: what this host's toolchain discovery actually finds

- **Canonical location:** The development host, read directly through `shutil.which`.
  Documentation for the function consulted:
  `https://docs.python.org/3/library/shutil.html`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the machine reporting its own state.
- **Supports:** `PATHEXT` is set and carries 13 entries. `git`, `py` and `powershell`
  each resolve; `pwsh` does not, and a deliberately absent name does not.
  `sys.prefix != sys.base_prefix`, so this interpreter is inside a virtual environment,
  which is what `runtime-contract.toml` requires and what
  `phase_017_sources.md` S-07 and S-08 established the shape of.
- **Implication for GLOBIN:** `pwsh` being absent while `powershell` is present is the
  case the optional classification exists for: PowerShell 7 is not installed here, the
  repository's own scripts invoke Windows PowerShell, and a required-capability model
  would have blocked start-up over a tool nothing needs. It is recorded so that the
  distinction between the two is a measurement rather than an assumption about what
  "PowerShell" means on a Windows host.

### S-11 — Probe: an RSA-4096 key in PEM form does not fit the credential blob; Ed25519 fits thirty times over

- **Canonical location:** The development host, measured with OpenSSL 3.5.5. The key
  types under test are the ones the venue documents:
  `https://developers.binance.com/docs/binance-spot-api-docs/faqs/api_key_types`
- **Accessed:** 2026-08-18
- **Authority:** Primary — the machine reporting its own state. S-15 of the Phase 020
  ledger names this as "a **measurement Phase 028 owes on the real host**, not
  something asserted here".
- **Supports:** Throwaway keys were generated in a scratch directory outside the
  repository, their encoded lengths measured, and the directory destroyed; no key
  material was printed, retained or committed. Against the 2560-byte ceiling of S-05:

  | Encoded form | Bytes | Fits |
  |---|---:|:--:|
  | Ed25519 private, PKCS#8 PEM | 122 | yes |
  | Ed25519 private, PKCS#8 DER | 48 | yes |
  | RSA-2048 private, PKCS#8 PEM | 1732 | yes |
  | RSA-2048 private, PKCS#8 DER | 1191 | yes |
  | **RSA-4096 private, PKCS#8 PEM** | **3324** | **no** |
  | RSA-4096 private, PKCS#8 DER | 2348 | yes, by 212 bytes |

- **Implication for GLOBIN:** The open question S-15 left is now answered, and the
  answer is not uniformly "yes". Binance supports 2048- and 4096-bit RSA keys, and **the
  4096-bit form a person actually handles — PEM, which is what a key file contains and
  what gets pasted — exceeds the platform ceiling by 764 bytes.** It fits only if
  re-encoded to DER, and then with 212 bytes of headroom, which is too little to spend
  on any envelope, versioning or metadata. So the store refuses an oversized value with
  a bounded reason that names the ceiling, rather than letting the operator meet
  `RPC_X_BAD_STUB_DATA` from S-05 and guess.
  It also gives GLOBIN a **measured** reason to prefer the key type Binance already
  recommends, rather than an appeal to that recommendation: Ed25519 at 122 bytes leaves
  the ceiling irrelevant, and S-16 records a Binance surface that accepts nothing else.
  Nothing here selects a key type — that is Phases 029 and 038 — but a constraint that
  would have been discovered by a failed write in a later phase is now a documented
  refusal in this one.

---

## What this ledger does not establish

| Question | Where it belongs |
|---|---|
| How a credential is collected from an operator, and validated before first use | Phase 029 |
| The wider health-check suite a long-running process needs | Phase 030 |
| Behaviour when the network, GPU or optional native components are unavailable | Phase 031 |
| Which permissions a Binance key carries, and what an environment *is* | Phases 035 and 039 |
