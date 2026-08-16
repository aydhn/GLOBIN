# Phase 020 — Source Ledger

Dependency Resolution and Lockfile Strategy; what a lock file records, what this
project's installer actually writes into one, and — for the specification half of
the phase — what the Windows credential store offers a later phase to build on.

Every claim Phase 020 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

The phase has two halves and they rest on different kinds of evidence, so this
ledger is in two parts. The first records what `pip` and `pip-audit` do, and an
unusual proportion of it is read from **installed source** rather than from
published documentation. That is deliberate and it is stated rather than hidden:
the shape of what `pip lock` emits decides which checks
[`../engineering/lock-policy.toml`](../engineering/lock-policy.toml) can ask for,
and four of the load-bearing facts are documented nowhere. Under
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) a project's own source is primary for
that project's behaviour, and a version is recorded with each so the claim can be
rechecked when the version moves.

The second part records what Windows offers a credential store. **Nothing in this
phase implements one.** Those entries exist because
[ADR-0048](../adr/0048-a-secret-lives-outside-the-tree-and-is-redacted-before-a-record-exists.md)
chose the store's properties as capabilities rather than mechanisms, *"so that
Phase 028 can satisfy them with whatever Windows actually offers"* — and left
establishing what Windows offers to whoever came next. These are that
establishment, and they are what
[`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md)
derives its limits from.

---

## What a lock file is, and what this project's installer writes into one

### S-01 — A lock file has a standard name, a standard shape, and a version field

- **Canonical location:** PEP 751, *A file format to record Python dependencies for
  installation reproducibility* — `https://peps.python.org/pep-0751/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the specification that defines the format.
- **Supports:** The file is "designed to be human-readable and machine-generated, so
  that installers consuming the file can calculate what to install without the need
  for dependency resolution at install-time." On naming: a lock file "must be named
  `pylock.toml` or match the regular expression `r"^pylock\.([^.]+)\.toml$"` if a
  name for the lock file is desired or if multiple lock files exist."
- **Implication for GLOBIN:** Two things follow, and both are structural rather than
  stylistic. The name is **not ours to choose** — `pylock.dev.toml` is the
  spec-legal spelling of a non-default lock, and Phase 021's runtime lock will have
  to be `pylock.toml` exactly. That is why
  [`../engineering/REPOSITORY_LAYOUT.md`](../engineering/REPOSITORY_LAYOUT.md) gains
  a lock row placing both at the repository root rather than under `docs/`. And
  "without the need for dependency resolution at install-time" is precisely the
  property this phase is buying: the installed set stops depending on when the
  install happened.

### S-02 — `pip lock` is experimental, and its output is valid for one interpreter and one platform

- **Canonical location:** pip documentation, *pip lock* —
  `https://pip.pypa.io/en/stable/cli/pip_lock/`; also the command's own `--help`
  output in this project's environment, pip 26.1.1.
- **Accessed:** 2026-08-16
- **Authority:** Primary — the tool's own documentation, confirmed against the
  installed build.
- **Supports:** The command's description opens "EXPERIMENTAL - Lock packages and
  their dependencies from:" and states "The generated lock file is only guaranteed
  to be valid for the current python version and platform." The output option reads
  "-o, --output <path> Lock file name (default=pylock.toml)."
- **Implication for GLOBIN:** Two consequences, one of which shapes the whole gate.
  The lock is valid for **the host that produced it**, and `pip lock` offers no
  `--python-version`, `--platform` or `--abi` to target another — so the lock serves
  the interpreter [`../engineering/runtime-contract.toml`](../engineering/runtime-contract.toml)
  pins and nothing else, and the 3.12 entry in the CI matrix cannot install from it.
  That is why the exact version pins in `.github/workflows/` survive this phase
  rather than being replaced. And the EXPERIMENTAL label is the stated reason
  `python -m tools.quality lock` recomputes every claim from the lock's own evidence
  instead of trusting the file, and the reason `bootstrap` keeps a `--from-pins`
  hand-crank.

### S-03 — What pip's lock writer actually records, which is a small subset of PEP 751

- **Canonical location:** pip 26.1.1 source, as installed in this project's
  environment — `pip/_internal/utils/pylock.py`, function
  `pylock_from_install_requirements` (lines 116-129). Published at
  `https://github.com/pypa/pip`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the implementation is authoritative for what the
  implementation writes. Nothing in pip's published documentation states this.
- **Supports:** The function returns `Pylock(lock_version=Version("1.0"),
  created_by="pip", packages=sorted(...))` and sets no other field. A rendered lock
  therefore carries `lock-version`, `created-by`, and per package a `name`, a
  `version`, and `[[packages.wheels]]` entries each holding a `name`, a `url` and a
  `[packages.wheels.hashes]` table.
- **Implication for GLOBIN:** This is the single fact that most shapes the gate.
  There is **no `requires-python`** in a pip-produced lock, no `environments`, no
  per-package markers, no index, no dependency edges and no `created-by` version.
  Three checks a reader would expect therefore cannot be written, and
  [`../engineering/DEPENDENCY_LOCKING.md`](../engineering/DEPENDENCY_LOCKING.md)
  says so rather than implying a coverage the gate does not have: the lock's own
  interpreter requirement cannot be compared against the runtime contract, which is
  why `lock-policy.toml` records the target beside the lock; and the absence of
  dependency edges means a package that is neither a declared root nor reachable
  from one is indistinguishable from an ordinary transitive one, so the gate
  compares **roots** in both directions and closes the orphaned-transitive case by
  relocking rather than by inspection.

### S-04 — pip writes the lock without controlling line endings

- **Canonical location:** pip 26.1.1 source — `pip/_internal/commands/lock.py`,
  line 173. Published at `https://github.com/pypa/pip`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the implementation.
- **Supports:** The command writes with `output_file_path.write_text(pylock_toml,
  encoding="utf-8")`, passing no `newline` argument, so Python's default newline
  translation applies and the file is written with CRLF on Windows.
- **Implication for GLOBIN:** `.gitattributes` stores `*.toml` with LF, so a lock
  written straight out of `pip lock` disagrees with the lock as committed. The gate
  normalises on write and **digests the LF-normalised text rather than the raw
  bytes**, so a CRLF working copy and an LF one produce the same evidence. A
  determinism check comparing raw bytes here would fail for a reason that has
  nothing to do with dependencies.

### S-05 — pip installs from a lock file, experimentally

- **Canonical location:** pip documentation, *pip install* and *pip lock*, the
  `--requirement` option — `https://pip.pypa.io/en/stable/cli/pip_install/`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the tool's own documentation, confirmed against pip
  26.1.1's `--help` output in this environment.
- **Supports:** "The file or URL can be in pip's requirements.txt format, or
  pylock.toml format. pylock.toml support is experimental."
- **Implication for GLOBIN:** This is what makes the lock load-bearing rather than
  decorative: `scripts/bootstrap.ps1` builds `.venv` from `pylock.dev.toml`, so the
  set the gate checks is the set that is installed. It is also the second
  EXPERIMENTAL surface this phase depends on, in the one command somebody runs
  before they have a working tree — which is why an unreadable lock is a **refusal**
  rather than a silent fall back to the pins, and why `--from-pins` exists as a
  deliberate act rather than as an automatic one.

### S-06 — `pip-audit` reads a lock without resolving it, and refuses an empty one

- **Canonical location:** pip-audit 2.9.0 source, as installed in this project's
  environment — `pip_audit/_dependency_source/pylock.py`, class `PyLockSource`
  (lines 20-88), and `pip_audit/_cli.py`. Published at
  `https://github.com/pypa/pip-audit`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the implementation, for the implementation's behaviour.
  The `--locked` flag itself is documented: "audit lock files from the local Python
  project. This flag only applies to auditing from project paths."
- **Supports:** `_collect_from_packages` yields `ResolvedDependency(name,
  Version(version))` straight from each entry and never resolves anything; a package
  with no version yields `SkippedDependency(name, "no version specified")`. A lock
  with no packages raises `PyLockSourceError(f"{filename}: missing packages in
  lockfile")`, and a lock whose `lock_version.major != 1` raises "lockfile version
  ... is not supported". The flag reaches this source only through a **project
  path**, which is globbed for `pylock.*.toml`; `-r` goes through a different parser
  and does not accept a lock.
- **Implication for GLOBIN:** Two things. First, switching
  `tools/quality/supply/audit.py` to `--locked` makes the audited set exactly the
  locked set — where today it synthesises a requirements file and lets `pip-audit`
  resolve it against a live index, so the audit describes a resolution nobody has
  installed and which can differ between two runs on the same commit. Second, and
  decisively: **an empty lock is not merely useless, it hard-fails the audit.**
  `project.dependencies` is empty and a contract test keeps it that way, so a
  runtime `pylock.toml` created in this phase would break the vulnerability gate
  this phase is strengthening. That is why only the toolchain is locked, and why the
  runtime lock is Phase 021's with `LOCK_RUNTIME_UNLOCKED` enforcing the pairing.

### S-07 — Locking a dependency group changes nothing in what pip records

- **Canonical location:** PEP 735, *Dependency Groups in pyproject.toml* —
  `https://peps.python.org/pep-0735/`; and pip 26.1.1 source,
  `pip/_internal/utils/pylock.py`.
- **Accessed:** 2026-08-16
- **Authority:** Primary — the specification for the feature, the implementation for
  what adopting it would produce.
- **Supports:** pip 26.1.1 accepts `--group` on `pip lock`. Its lock constructor
  (S-03) never sets the `dependency-groups` or `default-groups` fields PEP 751
  defines, and its TOML dictionary factory drops every field left unset, so a lock
  produced through `--group` renders identically to one produced through
  `-r`.
- **Implication for GLOBIN:** Adopting PEP 735 in this phase would change how
  dependencies are *declared* — touching `project.optional-dependencies`, the
  inventory reader, the drift gate and three contract tests — for **no observable
  difference in the artefact this phase delivers**. The roadmap's purpose for Phase
  020 is the locking mechanism and the resolution, upgrade and audit procedures, not
  the declaration format. It is recorded as considered and deferred in
  [`../engineering/DEPENDENCY_LOCKING.md`](../engineering/DEPENDENCY_LOCKING.md),
  owned by Phase 021, where a runtime dependency makes the extra-versus-group
  distinction visible for the first time.

---

## What the Windows credential store offers a later phase

Nothing below is implemented in this phase. Each entry establishes a limit inside
which Phases 026 to 029 must choose, and each is recorded so that the choice is made
against a measurement rather than an assumption.

### S-08 — The credential blob has a documented ceiling; the name has a much larger one, and is case-insensitive

- **Canonical location:** Microsoft Learn, *CREDENTIALW (wincred.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the platform vendor's reference for the structure.
- **Supports:** Of `CredentialBlobSize`: "This member cannot be larger than
  **CRED_MAX_CREDENTIAL_BLOB_SIZE** (5\*512) bytes." Of `TargetName` under a generic
  credential: "this member should identify the service that uses the credential in
  addition to the actual target. Microsoft suggests the name be prefixed by the name
  of the company implementing the service", and it "cannot be longer than
  **CRED_MAX_GENERIC_TARGET_NAME_LENGTH** (32767) characters." Also: "This member is
  case-insensitive", and "The **TargetName** and **Type** members uniquely identify
  the credential. This member cannot be changed after the credential is created.
  Instead, the credential with the old name should be deleted and the credential
  with the new name created." Of persistence: `CRED_PERSIST_LOCAL_MACHINE` is
  "visible to other logon sessions of this same user on this same computer and not
  visible to logon sessions for this user on other computers", while
  `CRED_PERSIST_ENTERPRISE` is additionally visible "to logon sessions for this user
  on other computers".
- **Implication for GLOBIN:** Four constraints, and the last two are the ones a
  designer would otherwise discover late. The **2560-byte ceiling** is the real
  limit on what may be stored, which makes the shape of the secret and the choice of
  store one question rather than two — see S-15. The 32767-character name budget
  means a deterministic, verbose, vendor-prefixed key is what the platform expects,
  so length never constrains the namespace builder. **Case-insensitivity is a
  correctness requirement on that builder**: two keys differing only in case are one
  credential, so the builder normalises case or the environment isolation it is
  supposed to provide is not real. And a name cannot be edited, so any change to the
  namespace scheme is a delete-and-recreate migration rather than a rename — which
  is why the scheme is fixed by a written contract before anything writes to a store.

### S-09 — A credential belongs to a logon session, and some logons have no credential set at all

- **Canonical location:** Microsoft Learn, *CredReadW function (wincred.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the platform vendor's reference for the function.
- **Supports:** "The CredRead function reads a credential from the user's credential
  set. The credential set used is the one associated with the logon session of the
  current token. The token must not have the user's SID disabled." Among its status
  codes, `ERROR_NO_SUCH_LOGON_SESSION`: "The logon session does not exist or there
  is no credential set associated with this logon session. Network logon sessions do
  not have an associated credential set."
- **Implication for GLOBIN:** This is the honest scope of the protection, and
  [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md)
  states it rather than letting "the operating system protects it" stand unqualified:
  the store separates **one account from another**, not one process from another
  process of the same account. Anything running as the user can read what the user
  stored. It also means availability is not universal — a logon with no credential
  set is a state to be recorded and refused, in the manner
  [ADR-0045](../adr/0045-a-platform-capability-is-a-recorded-state-never-a-pass.md)
  requires, never a crash and never a quiet fall back to somewhere less protected.

### S-10 — A write replaces, and the platform offers no compare-and-swap

- **Canonical location:** Microsoft Learn, *CredWriteW function (wincred.h)* —
  `https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the platform vendor's reference for the function.
- **Supports:** "The **CredWrite** function creates a new credential or modifies an
  existing credential in the user's credential set." And in its remarks: "This
  function creates a credential if a credential with the specified **TargetName**
  and **Type** does not exist. If a credential with the specified **TargetName** and
  **Type** exists, the new specified credential replaces the existing one." The one
  flag defined, `CRED_PRESERVE_CREDENTIAL_BLOB`, states "The credential BLOB from an
  existing credential is preserved with the same credential name and credential
  type. The **CredentialBlobSize** of the passed in *Credential* structure must be
  zero."
- **Implication for GLOBIN:** Rotation cannot borrow atomicity from the platform.
  There is no conditional write, no version token and no exchange — the sole flag
  *preserves* an existing value, which is not the same as *comparing* one. So the
  write-then-verify-then-retire procedure in
  [`../security/SECRET_STORE_CONTRACT.md`](../security/SECRET_STORE_CONTRACT.md) is
  constructed rather than inherited, and its ordering is the whole of the guarantee
  that a failed rotation leaves the previous credential resolvable.

### S-11 — Data protection binds to the user and the computer, with documented exceptions and one deprecation

- **Canonical location:** Microsoft Learn, *CryptProtectData function* —
  `https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the platform vendor's reference for the function.
- **Supports:** "Typically, only a user with logon credentials that match those of
  the user who encrypted the data can decrypt the data. In addition, decryption
  usually can only be done on the computer where the data was encrypted. However, a
  user with a roaming profile can decrypt the data from another computer on the
  network." Of `CRYPTPROTECT_LOCAL_MACHINE`: "When this flag is set, it associates
  the data encrypted with the current computer instead of with an individual user.
  Any user on the computer on which CryptProtectData is called can use
  CryptUnprotectData to decrypt the data." The page also records that the
  prompt-based flow "is deprecated and will be removed in February 2027."
- **Implication for GLOBIN:** "Typically" and "usually" are the platform's own
  hedges and they survive into GLOBIN's prose rather than being rounded up into a
  guarantee — a roaming profile, and the enterprise persistence scope in S-08, both
  mean "bound to this machine" is a default rather than a promise, and that is what
  the lost-machine section of the contract has to be written against.
  `CRYPTPROTECT_LOCAL_MACHINE` is refused outright, because it widens the audience
  from one account to every account on the box. And anything built on the
  prompt-based flow would ship with a known expiry, so the contract names it as
  refused rather than leaving a later phase to find out.

### S-12 — Microsoft's password guidance, including the one recommendation Python cannot follow

- **Canonical location:** Microsoft Learn, *Handling Passwords* —
  `https://learn.microsoft.com/en-us/windows/win32/secbp/handling-passwords`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the platform vendor's security best-practice guidance.
- **Supports:** "Never hardcode passwords, API keys, connection strings, or other
  secrets in source code." "Collect passwords as late as possible and discard them
  as early as possible." "Never log passwords or secrets. Ensure diagnostic logging,
  event logs, and crash dumps do not contain credential material." And: "When you
  have finished using passwords or secrets in memory, immediately overwrite the
  buffer by calling SecureZeroMemory. Unlike memset, the compiler cannot optimize
  away SecureZeroMemory."
- **Implication for GLOBIN:** Three of these are already rules here, and
  [`../security/SECURITY_BASELINE.md`](../security/SECURITY_BASELINE.md) owns them.
  The fourth is the one worth recording because GLOBIN **cannot** follow it and
  should not pretend to: CPython offers no equivalent for a `str`, whose objects are
  immutable, may be interned, and are copied and moved by the interpreter and its
  allocator, so no code here can establish that a value has been erased from
  process memory. The contract therefore claims **bounded lifetime and no
  persistence** and never erasure, and discharges Microsoft's actual principle —
  collect late, discard early — through resolution scope rather than through a
  memset that would not do what it appears to.

### S-13 — `getpass` suppresses echo, and documents the case where it cannot

- **Canonical location:** Python documentation, `getpass` —
  `https://docs.python.org/3/library/getpass.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the standard library's own documentation.
- **Supports:** "Prompt the user for a password without echoing." "If echo free
  input is unavailable getpass() falls back to printing a warning message to stream
  and reading from sys.stdin and issuing a GetPassWarning." And `GetPassWarning` is
  "A UserWarning subclass issued when password input may be echoed."
- **Implication for GLOBIN:** The fallback is a documented **echoing** path, so
  "collect it with `getpass`" is not by itself sufficient. The contract requires
  `GetPassWarning` to abort collection rather than merely warn: the suite already
  runs with `filterwarnings = ["error"]`, so it is an error under test, and this
  makes it an error at runtime too — which is where the operator actually is, and
  the only place the echoed value would reach a terminal history.

### S-14 — What `keyring`'s Windows backend does, recorded as a property of a candidate rather than as a choice

- **Canonical location:** `keyring` project documentation —
  `https://keyring.readthedocs.io/en/latest/` — and its Windows backend source at
  `https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py`
- **Accessed:** 2026-08-16
- **Authority:** Primary for that project's own behaviour, per
  [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) — upstream documentation is
  authoritative for the library it documents. Read from the project's main branch,
  so it is version-dependent and must be rechecked against a pinned release before
  anything is adopted.
- **Supports:** `WinVaultKeyring` writes with `CRED_TYPE_GENERIC` and a `Persist`
  value whose descriptor default is `CRED_PERSIST_ENTERPRISE`; it composes its
  target name from the user name and the service name rather than taking one; and
  the module records that it writes in UTF-16 while reading UTF-8 for backward
  compatibility. The published documentation lists the Windows Credential Locker
  among its recommended backends.
- **Implication for GLOBIN:** **This selects nothing.** `keyring` is not a declared
  dependency, has no entry in
  [`../engineering/wheel-survey.toml`](../engineering/wheel-survey.toml), and
  adopting it would require both a written review under
  [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) and a runtime dependency,
  which is Phase 021's to open. It is recorded because three of its properties bear
  directly on limits established above and are much cheaper to know now than to
  discover afterwards: the persistence default is the roaming one (S-08, S-11); the
  library composing its own target name would collide with the single-builder rule;
  and a UTF-16 blob consumes the 2560-byte budget twice as fast as its character
  count suggests.

---

## What the future authentication layers will have to hold

Recorded to establish what kind of material the store must be able to carry.
**No signing, no request and no session is implemented in this phase**; Phase 038
owns request signing and Phases 033 onwards the surfaces it applies to.

### S-15 — Binance recommends asymmetric API keys, and deprecates the symmetric ones

- **Canonical location:** Binance Developer Documentation, *API Key Types* —
  `https://developers.binance.com/docs/binance-spot-api-docs/faqs/api_key_types`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the venue's own documentation, which
  [ADR-0004](../adr/0004-official-apis-only-no-scraping.md) makes the only
  admissible source for a claim about Binance.
- **Supports:** "HMAC keys are deprecated. We recommend to migrate to asymmetric API
  keys, such as Ed25519 or RSA." "We recommend to use Ed25519 API keys as it should
  provide the best performance and security out of all supported key types." "We
  support 2048 and 4096 bit RSA keys."
- **Implication for GLOBIN:** The material a store will be asked to hold is not
  necessarily a short opaque string, so the 2560-byte ceiling in S-08 and the choice
  of key type are one question. Whether a given key's encoded form fits is a
  **measurement Phase 028 owes on the real host**, not something asserted here — see
  the closing section. The convergence worth recording is that the key type this
  venue recommends is also the one most comfortably inside the platform's limit.

### S-16 — A FIX session accepts one key type only, and the permissions have names

- **Canonical location:** Binance Developer Documentation, *FIX API* —
  `https://developers.binance.com/docs/binance-spot-api-docs/fix-api`
- **Accessed:** 2026-08-16
- **Authority:** Primary — the venue's own documentation.
- **Supports:** "FIX sessions only support Ed25519 keys." The `Username (553)` field
  "is required to contain the API key", and `RawData (96)` "is required to contain a
  valid signature made with the API key". The page further records that an Order
  Entry session requires the `FIX_API` permission, while Drop Copy and Market Data
  sessions accept either `FIX_API` or `FIX_API_READ_ONLY`.
- **Implication for GLOBIN:** `SECURITY_BASELINE.md`'s existing rule that a key
  carries the narrowest permission set the phase needs now has **real named grants**
  to be narrow about, established as fact rather than assumed from the shape of
  other venues. It also pins one end of the key-type question: a surface exists that
  accepts nothing but Ed25519, so a store that could not carry an Ed25519 key would
  foreclose it. Nothing about the signature payload, session logon, sequence numbers
  or connection limits is recorded here, because none of it is this phase's and
  recording it would invite building against it early.

---

## What was not established, and why

**Whether an encoded RSA key fits inside the credential blob.** The 2560-byte
ceiling (S-08) is primary and certain. Whether a particular encoded private key
exceeds it depends on the encoding chosen, on whether it is itself encrypted, and on
line wrapping, and no primary source states the resulting length. The contract
therefore states the **ceiling** as fact and the **fit** as a measurement Phase 028
owes. It does not assert that an RSA key does not fit.

**What Windows returns when a blob exceeds the limit.** Not stated on any page read
for this ledger. No error code is named anywhere in this phase's output.

**The exact byte cost of `keyring`'s UTF-16 encoding against that ceiling.** The
encoding is recorded in the library's own source (S-14); the arithmetic against 2560
is inference, and is written as derived rather than measured.

**Whether Binance offers address restriction or expiry for a given key type or
product.** `SECURITY_BASELINE.md` writes those as constraints on a decision rather
than as claims about the venue, and
[ADR-0006](../adr/0006-product-and-environment-capability-matrix.md) governs how the
venue's real capabilities are established when a phase needs them. Nothing here
asserts any of it.

**No index was contacted for the second half of this ledger**, and no Binance
endpoint was called for either half. Every Binance entry above is read from
published documentation, which is the only thing
[ADR-0004](../adr/0004-official-apis-only-no-scraping.md) permits.

**No credential of any kind was created, read, or written** in the course of
establishing any of this. The Windows entries are documentation claims about an API
this repository does not call.
