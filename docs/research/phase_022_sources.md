# Phase 022 — Source Ledger

Scientific Stack Installation and Verification, and the runtime filesystem and
lifecycle delivered alongside it. What the standard library guarantees about
file locking, atomic replacement, signals and interpreter exit; what Windows
documents about where a per-user application may write; and what `numpy` and
`pandas` state about the numeric behaviour this phase probes.

Every claim Phase 022 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

**Two kinds of entry appear below, and the difference is stated in each
`Authority` line.** Most record what a primary document *specifies*. Four record
what was *measured on the target host* — because "this host's `float64` is
binary64" and "this lock is genuinely cross-process" are claims about a machine,
and a specification cannot establish them. Where both exist, the specification
gives the contract and the measurement gives the evidence that this host honours
it. Neither substitutes for the other, and
[ADR-0058](../adr/0058-the-scientific-stack-is-verified-by-measurement-and-stays-in-the-approximate-regime.md)
is built on exactly that distinction.

---

## Single-instance locking

### S-01 — `msvcrt.locking` with `LK_NBLCK` does not block, and raises `OSError` when the region is held

- **Canonical location:** `https://docs.python.org/3/library/msvcrt.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary. CPython's own documentation of the module it ships.
- **Supports:** `msvcrt.locking(fd, mode, nbytes)` "Lock part of a file based on
  file descriptor `fd` from the C runtime. Raises `OSError` on failure. The locked
  region of the file extends from the current file position for `nbytes` bytes,
  and may continue beyond the end of the file." `LK_NBLCK` "Locks the specified
  bytes. If the bytes cannot be locked, `OSError` is raised." `LK_UNLCK` "Unlocks
  the specified bytes, which must have been previously locked."

- **Implication for GLOBIN:** The acquisition is non-blocking by choice of mode,
  which is what lets a second coordinator fail closed immediately instead of
  hanging. Because the region is measured *from the current file position*, the
  lock and the matching unlock must agree on both position and length — GLOBIN
  locks one byte at position zero and unlocks the same one byte, and never seeks
  the descriptor in between. The documented failure is `OSError`, so nothing in
  the adapter may catch a narrower type.

### S-02 — the lock is genuinely cross-process, and the operating system releases it when the holder exits

- **Canonical location:** `https://docs.python.org/3/library/msvcrt.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary, **by measurement on the target host** — Windows 11 Pro
  26200, CPython 3.14.5, `AMD64`. The documentation above specifies the API; it
  does not state what a *second process* observes, which is the property the
  whole single-instance design rests on.
- **Supports:** With one process holding `LK_NBLCK` over one byte of
  `instance.lock`, a separate `subprocess` attempting the same acquisition
  received `PermissionError` with `errno 13`. After the first process issued
  `LK_UNLCK` and closed the descriptor, a third process acquired the same region
  successfully.

- **Implication for GLOBIN:** Ownership is decided by the *result of an
  acquisition* and never by the presence of the file, which a crashed process
  leaves behind. The refusal is recognised as `OSError` with `errno == errno.EACCES`.
  Because Windows releases the region when the holding process ends, a stale lock
  file is harmless and must not be deleted on a guess — see
  [ADR-0059](../adr/0059-the-mutable-runtime-tree-is-user-local-and-one-coordinator-is-proved-by-a-lock.md).

---

## Atomic publication

### S-03 — `os.replace` overwrites the destination, and `os.fsync` requires a prior `flush`

- **Canonical location:** `https://docs.python.org/3/library/os.html#os.replace`
- **Accessed:** 2026-08-16
- **Authority:** Primary. CPython's documentation, and the interpreter's own
  docstrings read from the pinned 3.14.5 build for the text quoted first.
- **Supports:** `os.replace` is documented as "Rename a file or directory,
  overwriting the destination." `os.fsync(fd)` will "Force write of file with
  filedescriptor `fd` to disk. On Unix, this calls the native `fsync()` function;
  on Windows, the MS `_commit()` function," and the docs give the required order
  explicitly: "If you're starting with a buffered Python file object `f`, first do
  `f.flush()`, and then do `os.fsync(f.fileno())`, to ensure that all internal
  buffers associated with `f` are written to disk."

- **Implication for GLOBIN:** The publication sequence is fixed by this and not
  negotiable: write to a temporary file, `flush()`, `os.fsync(fileno())`, close,
  then `os.replace()`. `Path.rename` is not used because it does not overwrite an
  existing destination on Windows, which is precisely the case every republication
  hits. The temporary file is created **in the destination's own directory**, since
  a rename is only atomic within one filesystem — putting it in the platform
  temporary directory would silently turn the atomic step into a copy.

---

## Process lifecycle

### S-04 — Windows accepts seven signals, and a Python handler runs on the main thread at a bytecode boundary

- **Canonical location:** `https://docs.python.org/3/library/signal.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary. CPython's own documentation.
- **Supports:** "On Windows, `signal()` can only be called with `SIGABRT`,
  `SIGFPE`, `SIGILL`, `SIGINT`, `SIGSEGV`, `SIGTERM`, or `SIGBREAK`. A
  `ValueError` will be raised in any other case." On execution: "A Python signal
  handler does not get executed inside the low-level (C) signal handler. Instead,
  the low-level signal handler sets a flag which tells the virtual machine to
  execute the corresponding Python signal handler at a later point (for example,
  at the next bytecode instruction)." And: "Python signal handlers are always
  executed in the main Python thread of the main interpreter, even if the signal
  was received in another thread." The documentation further warns that
  "synchronization primitives such as `threading.Lock` should not be used within
  signal handlers. Doing so can lead to unexpected deadlocks."
- **Measured:** `hasattr(signal, ...)` on the target host reports `SIGINT`,
  `SIGTERM` and `SIGBREAK` present and `SIGHUP` absent.

- **Implication for GLOBIN:** Registration is guarded by `hasattr` rather than by
  a platform string, because an unsupported signal raises `ValueError` and a
  fail-closed start-up must not fall over while installing its own shutdown path.
  The handler sets an intent flag and returns — no I/O, no lock, no cleanup —
  which follows directly from the deadlock warning and from handlers running
  between bytecodes rather than at a quiescent point.

### S-05 — `atexit` does not run on an unhandled signal, a fatal error, or `os._exit`

- **Canonical location:** `https://docs.python.org/3/library/atexit.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary. CPython's own documentation.
- **Supports:** "The functions registered via this module are not called when the
  program is killed by a signal not handled by Python, when a Python fatal
  internal error is detected, or when `os._exit()` is called." They are called
  "upon normal interpreter termination", in reverse registration order.

- **Implication for GLOBIN:** `atexit` is registered as a best-effort net and
  nothing rests on it. A hard kill and a power loss are exactly the cases it does
  not cover, and they are exactly the cases crash safety is about — so crash
  safety comes from atomic publication (S-03) instead, and the cleanup that must
  happen is driven by `try`/`finally`. Presenting `atexit` as crash protection
  would be a claim this document refutes.

---

## Where a per-user application may write

### S-06 — `FOLDERID_LocalAppData`'s documented default path is `%LOCALAPPDATA%`

- **Canonical location:** `https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid`
- **Accessed:** 2026-08-16
- **Authority:** Primary. Microsoft's own Known Folder reference.
- **Supports:** `FOLDERID_LocalAppData`, GUID
  `{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}`, display name `Local`, folder type
  `PERUSER`, **Default Path `%LOCALAPPDATA%` (`%USERPROFILE%\AppData\Local`)**,
  CSIDL equivalent `CSIDL_LOCAL_APPDATA`, legacy default path
  `%USERPROFILE%\Local Settings\Application Data`.
- **Measured:** `LOCALAPPDATA` is present in the process environment on the target
  host.

- **Implication for GLOBIN:** Microsoft's own table gives `%LOCALAPPDATA%` as the
  spelling of this Known Folder, which is what makes reading the environment
  variable a *platform lookup* rather than a configuration source — the
  distinction that keeps this phase clear of Phase 027's deferral in
  [`../CONFIGURATION_POLICY.md`](../CONFIGURATION_POLICY.md). The folder is
  `PERUSER`, so two checkouts by one user share one runtime root, which is the
  intended behaviour for a single-coordinator lock. When the variable is absent
  the adapter refuses rather than falling back to `%USERPROFILE%` or the legacy
  path; `SHGetKnownFolderPath` is the recorded alternative if a redirected profile
  ever makes that insufficient.

---

## The scientific stack

### S-07 — copy-on-write is the only mode in pandas 3.0, and a derived object always behaves as a copy

- **Canonical location:** `https://pandas.pydata.org/docs/user_guide/copy_on_write.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary. The pandas project's own user guide.
- **Supports:** "Copy-on-Write is now the default with pandas 3.0" and
  "Copy-on-Write is the default and only mode in pandas 3.0. This means that users
  need to migrate their code to be compliant with CoW rules." The guarantee itself:
  "CoW means that any DataFrame or Series derived from another in any way always
  behaves as a copy. As a consequence, we can only change the values of an object
  through modifying the object itself."
- **Measured:** Mutating `parent["x"]` through a derived Series left
  `parent["x"].iloc[0]` unchanged. Separately, reading `pd.options.mode.copy_on_write`
  emits a `Pandas4Warning` stating the option is deprecated, can no longer be
  disabled, and will be removed in pandas 4.0.

- **Implication for GLOBIN:** The `pandas.copy_on_write_is_active` probe asserts
  the **behaviour** — a parent frame unchanged after its child is mutated — and
  never reads `mode.copy_on_write`. A probe that read the option would emit a
  deprecation warning today and fail outright on pandas 4, for a reason unrelated
  to whether GLOBIN's assumption still holds.

### S-08 — `numpy.float64` is IEEE-754 binary64 on this host, and `int64` overflow wraps observably

- **Canonical location:** `https://numpy.org/doc/stable/reference/arrays.scalars.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary, **by measurement on the target host** against numpy
  2.5.2. The reference documents the scalar types; whether this build's `float64`
  is binary64 is a property of the installed artefact, which is what
  `tools/quality/stack` exists to establish.
- **Supports:** `np.finfo(np.float64)` reports `nmant = 52`,
  `eps = 2.220446049250313e-16` (exactly `2**-52`) and `bits = 64`, and
  `np.dtype(np.float64).itemsize` is `8`. Division producing infinity and
  not-a-number propagates rather than raising, and `nan != nan` is `True`.
  `np.int64(2**63 - 1) + np.int64(1)` evaluates to `-9223372036854775808` **and
  emits a `RuntimeWarning`**.

- **Implication for GLOBIN:** These are the four facts
  [`../PRECISION_POLICY.md`](../PRECISION_POLICY.md)'s approximate regime is
  defined against, so they are probed rather than assumed. The overflow result is
  recorded as *observable* rather than merely wrapping: silence would be the
  dangerous outcome, and a warning means a later phase can escalate it. Nothing
  here licenses a `float` reaching a venue or a ledger — that door stays one-way.

### S-09 — pandas 3.0 keeps a UTC-aware timestamp as `datetime64[us, UTC]` through a round trip

- **Canonical location:** `https://pandas.pydata.org/docs/user_guide/timeseries.html`
- **Accessed:** 2026-08-16
- **Authority:** Primary, **by measurement on the target host** against pandas
  3.0.5.
- **Supports:** A `pd.Timestamp` constructed with a UTC offset and placed in a
  DataFrame column produced dtype `datetime64[us, UTC]`. The value read back
  compared equal to the original, retained `tz` of `UTC`, and its `tzinfo`
  compared equal to `datetime.timezone.utc`.

- **Implication for GLOBIN:** The `pandas.utc_timestamp_round_trip_preserves_the_instant`
  probe checks the rule [`../TIME_POLICY.md`](../TIME_POLICY.md) already sets —
  internal time is UTC and aware — at the boundary where it is most easily lost,
  since a dataframe silently dropping a timezone would produce naive timestamps
  that `ENGINEERING_CONTRACT.md` invariant 25 forbids crossing a domain boundary.
  The microsecond resolution is recorded because it is finer than the millisecond
  convention Phase 009 fixed for external representations, and the two must not be
  confused: this is storage precision, not the wire format.

---

## What this phase did not need to read

Naming these is what stops a reader assuming the ledger is thin because the
research was.

| Question | Why it is absent |
|---|---|
| Any Binance interface, endpoint or error code | This phase reaches no network, and Phases 033-048 own the API map |
| Named mutexes, `CreateMutexW`, Win32 error codes | `msvcrt` answered the question with the standard library; the Win32 route is recorded as a declined alternative in ADR-0059 |
| `SHGetKnownFolderPath` call semantics | Not called. S-06 makes the environment variable the documented spelling, and the `ctypes` route is a recorded fallback rather than an implementation |
| Upstream `numpy` and `pandas` test-suite design | ADR-0058 declines to run them, so how they work is not a fact this phase depends on |
| Filesystem semantics of network shares and redirected profiles | A recorded limitation of this design rather than a claim it makes; S-03's atomicity holds within one filesystem, and ADR-0059 says so |
