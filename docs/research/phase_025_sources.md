# Phase 025 — Source Ledger

TA-Lib's native library, and the CPython facilities a watchdog uses to find out
where a wedged process is stuck. What the wrapper's own project documents about
what its wheels contain, what CPython documents about frames, dumps and exits, and
what this host actually answers when asked.

Every claim Phase 025 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

**Two entries below record a trap rather than a specification.** S-05 is a property
of PyPI's API shape that produced a confident wrong answer during this phase and
was caught only by a second instrument. S-08 is a limit on the evidence this phase
collects, recorded because the documentation states it plainly and the code would
otherwise imply more than it can deliver.

**One thing is recorded as unread rather than omitted.** S-09 names a reference
entry that could not be retrieved, and says which claim therefore rests on a
different source.

---

## The TA-Lib wrapper and its native library

### S-01 — `ta-lib` 0.7.1 publishes a wheel for the pinned interpreter

- **Canonical location:** https://pypi.org/pypi/ta-lib/0.7.1/json
- **Accessed:** 2026-08-17
- **Authority:** Primary — the index's own metadata for one release.
- **Supports:** Version `0.7.1`, `requires_python` `>=3.9`, uploaded 2026-07-16.
  Its Windows files are `ta_lib-0.7.1-{cp39,cp310,cp311,cp312,cp313,cp314}-*-win_amd64.whl`,
  none yanked, and the `cp314` wheel is 920,544 bytes. `requires_dist` is
  `["build", "numpy"]`.

- **Implication for GLOBIN:** `ta_lib-0.7.1-cp314-cp314-win_amd64.whl` serves the
  interpreter `docs/engineering/runtime-contract.toml` pins, which is what let
  Phase 025 adopt the library rather than record a gap. Two consequences are
  recorded elsewhere rather than inferred here: there is no `cp314t` file, so the
  free-threaded gap `docs/engineering/wheel-survey.toml` used to track moved to an
  adopted library rather than closing; and `build` is a PEP 517 build *frontend*
  declared as an install requirement, which is why `pylock.toml` now also carries
  `build`, `packaging`, `pyproject_hooks` and `colorama`.

### S-02 — The wrapper is BSD 2-Clause, and its metadata does not say so

- **Canonical location:** https://github.com/ta-lib/ta-lib-python/blob/master/LICENSE
- **Accessed:** 2026-08-17
- **Authority:** Primary — the project's own licence file.
- **Supports:** The file is a two-clause BSD licence; the two conditions are the
  source-form and binary-form redistribution clauses and there is no third. PyPI
  serves `license: null` and `license_expression: null` for this release, and the
  only metadata signal is the classifier `License :: OSI Approved :: BSD License`.

- **Implication for GLOBIN:** `docs/engineering/dependency-reviews.toml` records
  `BSD-2-Clause` with the LICENSE file as its `licence_source`. Unlike `pandas` and
  `psutil`, no automated check could have established this identifier — the
  classifier does not distinguish two clauses from three, so the review had to read
  the file. Worth knowing before the next licence audit assumes the metadata is
  authoritative.

### S-03 — Binary wheels have carried the native C library since 0.6.5

- **Canonical location:** https://raw.githubusercontent.com/ta-lib/ta-lib-python/master/README.md
- **Accessed:** 2026-08-17
- **Authority:** Primary — the project's own README.
- **Supports:** *"For convenience, and starting with version 0.6.5, we now build
  binary wheels for different operating systems, architectures, and Python versions
  using GitHub Actions which include the underlying TA-Lib C library and are easy
  to install."* On the fallback path: *"In the event that your operating system,
  architecture, or Python version are not available as a binary wheel, it is fairly
  easy to install from source using the instructions above"*, and source
  installation requires the C library first — *"To use TA-Lib for python, you need
  to have the TA-Lib already installed."* The import name is `talib`.

- **Implication for GLOBIN:** This is the claim `ROADMAP.md` row 025 asks about,
  and it is a claim rather than a measurement — which is exactly why
  `docs/engineering/wheel-survey.toml` refused to conclude it from a filename and
  filed it against this phase. S-04 is the measurement. The documented fallback is
  what `docs/engineering/SCIENTIFIC_STACK.md` records for the case a future
  interpreter has no wheel.

### S-04 — On this host the wheel does carry it, and the library answers

- **Canonical location:** `.venv\Scripts\python.exe`, after
  `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1`
- **Accessed:** 2026-08-17
- **Authority:** Measured on the target host.
- **Supports:** The installed distribution reports version `0.7.1` and a `WHEEL`
  tag of `cp314-cp314-win_amd64` with `Root-Is-Purelib: false`. It ships **one**
  compiled artefact, `talib/_ta_lib.cp314-win_amd64.pyd` at 1,527,296 bytes, and no
  companion `.dll`. `talib.__ta_version__` is the bytes value
  `b'0.7.1 (Jul 16 2026 18:35:59)'`; `talib.get_functions()` returns 161 names
  across six groups; and `talib.SMA(numpy.arange(1.0, 21.0), timeperiod=5)` returns
  four leading `NaN` values and a final value of exactly `18.0`.

- **Implication for GLOBIN:** Three facts, and the first is the phase's answer. The
  C library replies with its own version, so it linked and initialised — nothing
  outside the wheel was installed on this host. The single `.pyd` with no companion
  library means it is linked into the extension rather than shipped beside it,
  though `docs/engineering/stack-contract.toml`'s probe deliberately does not
  *require* that shape, because a companion DLL would carry the library equally
  well. The warm-up length of `timeperiod - 1` is the seeding convention Phase 114's
  fallback must match, and the probe asserts it as an equality rather than a
  tolerance: an indicator seeded one bar short is look-ahead arriving as a plausible
  number. Note that `__ta_version__` is `bytes` and is not documented in the
  project's README, so its type is a measurement rather than a contract — the probe
  decodes defensively.

### S-05 — PyPI's aggregate JSON endpoint is not safe to read a version from

- **Canonical location:** https://pypi.org/pypi/ta-lib/json
- **Accessed:** 2026-08-17
- **Authority:** Measured against the index, and corroborated by S-01.
- **Supports:** A retrieval of this endpoint reported the latest version as `0.6.6`
  and listed Windows wheels for `cp310`–`cp313` only. Both statements are false:
  S-01 shows `0.7.1` exists with a `cp314` wheel, and
  `python -m tools.quality.wheels probe` — which queries the index directly —
  passed against the committed survey recording exactly that.

- **Implication for GLOBIN:** The endpoint's `releases` key holds every file of
  every release ever published, so a size-limited retrieval keeps the *earliest*
  entries and drops the ones being asked about. The answer that comes back is
  well-formed and wrong. Version facts written into `wheel-survey.toml`,
  `stack-contract.toml` or a dependency review must come from the per-version
  endpoint `https://pypi.org/pypi/<name>/<version>/json`, which is small and
  complete, or from `tools/quality/wheels probe`. This ledger's S-01 was re-read
  that way after the first answer was found to be wrong.

---

## The CPython facilities a watchdog uses

### S-06 — `sys._current_frames` exists for exactly this, and says so

- **Canonical location:** https://docs.python.org/3/library/sys.html#sys._current_frames
- **Accessed:** 2026-08-17
- **Authority:** Primary — the language reference.
- **Supports:** *"Return a dictionary mapping each thread's identifier to the
  topmost stack frame currently active in that thread at the time the function is
  called."* And on its purpose: *"This is most useful for debugging deadlock: this
  function does not require the deadlocked threads' cooperation, and such threads'
  call stacks are frozen for as long as they remain deadlocked."* It also states
  *"This function should be used for internal and specialized purposes only"* and
  that it raises an auditing event.

- **Implication for GLOBIN:** The documented purpose is the watchdog's purpose, and
  the "does not require the deadlocked threads' cooperation" clause is what makes it
  usable at all — the threads being described are by definition the ones that have
  stopped cooperating. `globin.adapters.watchdog.ProcessStackEvidence` is the only
  caller, and the underscore is why it lives in an adapter behind a port rather than
  being reached from anywhere. What it hands back are **live frame objects**, so the
  collector extracts summaries with `traceback.extract_stack` and drops the mapping
  in the same call: a frame's `f_locals` holds the values a credential-reading
  function was working with, not merely the name of the function reading them.

### S-07 — `faulthandler.dump_traceback` writes all threads, and `register` is not on Windows

- **Canonical location:** https://docs.python.org/3/library/faulthandler.html
- **Accessed:** 2026-08-17
- **Authority:** Primary — the language reference.
- **Supports:** `faulthandler.dump_traceback(file=sys.stderr, all_threads=True)` —
  *"Dump the tracebacks of all threads into file. If all_threads is False, dump only
  the current thread."* Of `faulthandler.register`: *"Not available on Windows."*

- **Implication for GLOBIN:** The watchdog calls `dump_traceback` explicitly rather
  than arranging for a signal to trigger one, which is the only option this host
  has: Phase 023 already recorded that `register` is POSIX-only and this confirms
  it from the same source. The dump goes to the handle Phase 023's `FaultFile`
  already holds open, so the collector performs no `open` and no `mkdir` — the
  strongest available bound on how long it can block, given that the call itself
  cannot be time-bounded from the calling thread.

### S-08 — A frame from a *live* thread may already be stale

- **Canonical location:** https://docs.python.org/3/library/sys.html#sys._current_frames
- **Accessed:** 2026-08-17
- **Authority:** Primary — the language reference.
- **Supports:** *"The frame returned for a non-deadlocked thread may bear no
  relationship to that thread's current activity by the time calling code examines
  the frame."*

- **Implication for GLOBIN:** A limit on what a stall incident's thread evidence
  means, and it is stated in `docs/engineering/RUNTIME_WATCHDOG.md` rather than
  implied. The stalled component's own stack is trustworthy, because that is the
  frozen case the documentation describes. Every *other* thread in the dump is a
  sample that may already have moved on, and an operator reading one should treat it
  as a hint about what the process was doing rather than as a record of where it
  was.

### S-09 — `sys.exit` cannot end a process from a background thread

- **Canonical location:** https://docs.python.org/3/library/sys.html#sys.exit
- **Accessed:** 2026-08-17
- **Authority:** Primary — the language reference.
- **Supports:** *"Since `exit()` ultimately 'only' raises an exception, it will only
  exit the process when called from the main thread, and the exception is not
  intercepted. Cleanup actions specified by finally clauses of try statements are
  honored, and it is possible to intercept the exit attempt at an outer level."*

- **Implication for GLOBIN:** This is the reason
  `globin.adapters.watchdog.ImmediateProcessExit` calls `os._exit`. The watchdog
  escalates from its own thread, so `sys.exit` there would raise `SystemExit` in
  that thread, end that thread, and leave the wedged process running — a silent
  failure of the one mechanism that must not fail silently. The second clause
  matters as much: honouring `finally` blocks is the wrong behaviour when the reason
  for escalating is that something is stuck inside one.

  **`os._exit`'s own reference entry could not be read.** The `os` module page
  truncates before reaching it, which is the same retrieval limit S-05 records. The
  decision above rests on what `sys.exit` documents about itself, which is verified,
  rather than on a claim about `os._exit` that this ledger has not confirmed. The
  properties GLOBIN relies on — no `atexit`, no buffer flush, no unwinding — are
  therefore recorded here as **unverified against primary documentation**, and the
  phase that has reason to depend on them more heavily should read that entry.
