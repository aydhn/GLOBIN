# Phase 009 — Research Source Ledger

Every external claim made by Phase 9 traces to an entry below. Entries are
summaries written for GLOBIN's purposes; documentation text is not copied into
this repository.

Phase 9 relies on external behaviour in three places: the standard library
modules the clock is built from, the venue's published timestamp convention —
which justifies a *convention*, not an integration — and the pytest and
coverage.py interfaces the execution tooling drives. It adds no dependency, and
it reaches nothing.

**Ledger conventions**

- `Authority: Primary` means the vendor or upstream project publishing its own
  behaviour. `Secondary` means anything else.
- Several entries record a fact **verified by running the code on this machine**
  (CPython 3.14.5, Windows 11), not only by reading it. Where that happened the
  entry says so, and gives the observed value.
- Where a fact could not be established from a primary source in this phase, the
  entry says so explicitly and names the phase that must resolve it.
- All accesses were performed on the date recorded in each entry.

---

## The Python clock surface

### S-01 — Python: `datetime.UTC`, and the deprecation of `utcnow`

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the language documenting its own standard library.
- **Supports:** `datetime.UTC` was added in 3.11 as an alias for
  `datetime.timezone.utc`. Both `datetime.utcnow()` and
  `datetime.utcfromtimestamp()` are deprecated since 3.12, and the documented
  replacements are `datetime.now(UTC)` and `datetime.fromtimestamp(ts, UTC)`.
  The stated rationale is that naive datetimes are treated by many `datetime`
  methods as local times, so aware datetimes are preferred for representing UTC.
- **Implication for GLOBIN:** `SystemClock.now` uses `datetime.now(UTC)`, and
  the deprecated spellings appear in the forbidden set that
  `tests/architecture/test_clock_discipline.py` enforces. The deprecation is not
  merely stylistic here: `pyproject.toml` sets `filterwarnings = ["error"]`, so
  reaching for `utcnow()` anywhere in this repository fails the suite rather
  than warning. `utcnow()` returning a *naive* datetime holding UTC is exactly
  the shape `ENGINEERING_CONTRACT.md` invariant 25 forbids from crossing a
  boundary.

### S-02 — Python: aware versus naive objects, and the exact test

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** an object is aware when `d.tzinfo is not None and
  d.tzinfo.utcoffset(d) is not None`. Both halves are required: a `tzinfo` whose
  `utcoffset` returns `None` leaves the object naive. `date` objects are always
  naive; a `datetime` may be either.
- **Implication for GLOBIN:** the refusal in `Instant.__post_init__` tests the
  offset rather than merely the presence of a `tzinfo`, because the second half
  of that condition is the one a hand-written check omits. `datetime` is also a
  *subclass* of `date`, so the type check is written against `datetime` — a
  check against `date` would silently admit a `datetime` while a bare `date` has
  no time of day to be an instant of.

### S-03 — Python: `datetime` resolution, and what `utcoffset` may raise

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `datetime.resolution` is `timedelta(microseconds=1)`.
  `utcoffset()` raises `TypeError` if the `tzinfo` returns something other than
  `None` or a `timedelta`, and `ValueError` if the offset is not strictly
  between `-timedelta(hours=24)` and `timedelta(hours=24)`. **Verified by
  running the code on this machine:** a `tzinfo` returning `'nope'` raised
  `TypeError: tzinfo.utcoffset() must return None or timedelta, not 'str'`, and
  one returning `timedelta(days=2)` raised the corresponding `ValueError`.
- **Implication for GLOBIN:** a `tzinfo` is arbitrary caller-supplied code, so
  asking a datetime for its offset is a call into a stranger's implementation
  rather than a field read. Both exceptions are translated into
  `ValidationError`, because [ADR-0022](../adr/0022-error-taxonomy-rooted-in-one-type.md)
  requires that a fault leaving a boundary is a `globin.errors` type. Microsecond
  resolution is why the millisecond conversion is lossy at all.

### S-04 — Python: `astimezone` can leave the representable range

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `datetime` represents years 1 through 9999, and converting an
  aware datetime to another zone shifts it by the offset. **Verified by running
  the code on this machine:** `datetime(1, 1, 1,
  tzinfo=timezone(timedelta(hours=14))).astimezone(UTC)` raised `OverflowError:
  date value out of range`.
- **Implication for GLOBIN:** the `instant()` factory wraps that `OverflowError`
  into a `ValidationError` naming the moment and the reason. It is far from any
  realistic input, which is precisely why it needed finding deliberately rather
  than being waited for — it is reachable only within a day of either end of the
  calendar, and the property strategies leave that day clear so the case is
  tested once, on purpose, rather than generated into every law.

### S-05 — Python: integer conversion from a `timedelta`, and why not `timestamp()`

- **Canonical location:** https://docs.python.org/3/library/datetime.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `timedelta` normalises itself into days, seconds and
  microseconds, all integers. `datetime.timestamp()` returns a `float`.
  **Verified by running the code on this machine:** for
  `datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)` the exact microsecond
  count computed from the `timedelta` fields is `253402300799999999`, while the
  same value routed through `timestamp()` yields `253402300800000000` — one
  microsecond into a moment that does not exist. The error runs in both
  directions: a 2286 value came back one microsecond short.
- **Implication for GLOBIN:** `Instant.epoch_millis` computes the microsecond
  count from the `timedelta`'s three fields and never through `timestamp()`.
  `MICROSECONDS_PER_DAY` exists for that arithmetic, and its docstring carries
  the measured figures so the choice is not re-litigated as premature caution.

### S-06 — Python: `time.monotonic` and its undefined reference point

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `monotonic()` returns "the value (in fractional seconds) of a
  monotonic clock, i.e. a clock that cannot go backwards", which "is not
  affected by system clock updates", and whose "reference point of the returned
  value is undefined, so that only the difference between the results of two
  calls is valid".
- **Implication for GLOBIN:** this is the entire justification for
  `MonotonicReading` being a type that cannot be rendered as a time and cannot
  produce epoch milliseconds. Offering either would claim a correspondence the
  platform explicitly declines to make. It is also why the type admits a
  negative reading: a sign rule would be a claim the source does not support.

### S-07 — Python: `time.time` can go backwards

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** "While this function normally returns non-decreasing values, it
  can return a lower value than a previous call if the system clock has been set
  back between the two calls."
- **Implication for GLOBIN:** the reason `Instant` defines no subtraction, and
  the reason wall time and monotonic time are two ports rather than one. An
  elapsed interval measured with the wall clock is correct until an operator or
  an NTP correction steps it mid-measurement, and the resulting defect is a
  quietly wrong number rather than an exception.

### S-08 — Python: `perf_counter`, and why the guarantee was chosen over the resolution

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `perf_counter()` is "a clock with the highest available
  resolution to measure a short duration", and "does include time elapsed during
  sleep". The `_ns` variants of all these functions exist to "avoid the
  precision loss caused by the float type". **Verified by running the code on
  this machine:** `time.get_clock_info` reports
  `implementation='QueryPerformanceCounter()'`, `monotonic=True`,
  `adjustable=False`, `resolution=1e-07` for **both** `monotonic` and
  `perf_counter`, and `implementation='GetSystemTimePreciseAsFileTime()'`,
  `monotonic=False`, `adjustable=True`, `resolution=1e-07` for `time`.
- **Implication for GLOBIN:** `SystemMonotonicClock` uses `monotonic_ns()`. On
  this host the two counters are the same source, so the choice costs nothing
  measurable and is made purely on which guarantee is documented — the right
  basis, because the declared host is not the only machine this will ever run
  on. `adjustable=True` on the wall clock is the concrete, measured evidence for
  S-07's consequence. The `_ns` note is why `Duration` counts nanoseconds as an
  `int` rather than seconds as a `float`.

### S-09 — Ruff: the `flake8-datetimez` (DTZ) family

- **Canonical location:** https://docs.astral.sh/ruff/rules/
- **Accessed:** 2026-08-14
- **Authority:** Primary — the linter documenting its own rules.
- **Supports:** the `DTZ` family flags naive constructions —
  `datetime()` without `tzinfo`, `datetime.now()` without `tz`, `utcnow()`,
  `utcfromtimestamp()`, `date.today()`, `fromtimestamp()` without `tz`, and
  `strptime` without `%z`. **No DTZ rule flags `time.time()`,
  `time.monotonic()` or `time.perf_counter()`**, and none constrains *where* a
  call may appear.
- **Implication for GLOBIN:** `DTZ` has been selected since Phase 004 and
  already enforces awareness repository-wide, which is why this phase did not
  need to add it. It is also why an additional check was necessary:
  `datetime.now(UTC)` inside the domain layer satisfies every DTZ rule and
  violates invariant 25. `tests/architecture/test_clock_discipline.py` enforces
  location, which is the half no lint rule covers.

---

## The venue's millisecond convention

### S-10 — Binance Spot API: timestamps are milliseconds by default

- **Canonical location:** https://developers.binance.com/docs/binance-spot-api-docs/rest-api/general-api-information
- **Accessed:** 2026-08-14
- **Authority:** Primary — the venue publishing its own interface.
- **Supports:** "All time and timestamp related fields in the JSON responses are
  in **milliseconds by default**." Microsecond precision is available only by
  sending an `X-MBX-TIME-UNIT` header. Timestamp parameters such as `startTime`,
  `endTime` and `timestamp` may be passed in either unit. `recvWindow`
  "specifies for how long the request stays valid and may only be specified in
  milliseconds"; it defaults to 5000 ms and may not exceed 60000 ms.
- **Implication for GLOBIN:** the sole reason a millisecond convention exists at
  all, and the reason it is a *projection* rather than the representation — the
  unit is a property of the wire, not of GLOBIN. `recvWindow` is also the
  concrete case behind the flooring decision in
  [ADR-0035](../adr/0035-milliseconds-are-a-floored-projection.md): the venue
  validates a request against a window around its own clock, so a timestamp that
  has drifted *forward* is the one at risk of rejection, and truncation towards
  the past is the safe direction. **Nothing in Phase 009 calls this API.** The
  entry justifies a convention; the integration is Phases 033-048, and
  reconciling the two clocks is **Phase 040**.

---

## The execution tooling

### S-12 — pytest: arguments read from a file, and what `argparse` does with them

- **Canonical location:** https://docs.pytest.org/en/stable/how-to/usage.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the project documenting its own interface.
- **Supports:** since pytest 8.2, `pytest @file` reads arguments from a file, one
  entry per line, in any of the selection formats the command line accepts. The
  mechanism is `argparse`'s `fromfile_prefix_chars`, which splits on
  `str.splitlines` and, with the default line converter, returns each line
  **verbatim** — so a blank line becomes an empty positional argument. Expansion
  is also recursive, so a line beginning with `@` is read as another file.
- **Implication for GLOBIN:** this is what makes shard execution possible with no
  plugin, and on Windows it is a necessity rather than a convenience: the command
  line is capped at 32 767 characters and 963 node IDs are roughly 60 KB of argv.
  The three behaviours above are why the args files carry no blank line and no
  trailing blank, and why a node ID beginning with `@` is refused when the
  manifest is parsed. **Verified by running it on this machine:** a two-line args
  file resolved both node IDs, and a stale one produced `ERROR: not found` with
  exit 4 rather than a silent skip.

### S-13 — pytest: node ID syntax, and the escaping inside a parametrised one

- **Canonical location:** https://docs.pytest.org/en/stable/how-to/usage.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** a node ID is a path, `::`, and the test name, with parameters in
  square brackets. **Verified by running collection on this machine:** all 963
  IDs use forward slashes on Windows, and four of them contain backslashes
  *inside the parameter part*, because pytest escapes special characters there —
  a TOML fixture containing a newline appears as a literal backslash-n, and a
  cedilla appears as a backslash-x escape.
- **Implication for GLOBIN:** forward slashes mean node IDs are platform-stable
  and can be hashed without normalisation. The escaping means a validator must
  treat the path part and the parameter part differently: a backslash before
  `::` is a platform difference that must surface, and one after it is pytest's
  own spelling. The first implementation refused both and silently dropped four
  tests; the parser's count self-check is what caught it.

### S-14 — pytest: the exit codes

- **Canonical location:** https://docs.pytest.org/en/stable/reference/exit-codes.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `0` all tests passed; `1` some failed; `2` interrupted by the
  user; `3` an internal error; `4` a command-line usage error; `5` no tests were
  collected.
- **Implication for GLOBIN:** only `0` and `1` are verdicts about tests, and the
  harness classifies everything else as unmeasured. Two matter especially: `5`
  read as success reports a shard that ran nothing as a shard that passed, which
  in a partition is the failure that makes the union claim false; and `4` is what
  pytest returns for a node ID that no longer exists, making collection drift
  something observed rather than inferred.

### S-15 — pytest: a unique base temporary directory per concurrent run

- **Canonical location:** https://docs.pytest.org/en/stable/how-to/tmp_path.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** temporary directories are created under
  `{temproot}/pytest-of-{user}/pytest-{num}/`, where the number auto-increments.
  Concurrent invocations of the same test function are supported by configuring
  the base temporary directory to be unique for each concurrent run, and when
  `pytest-xdist` is used the documentation says care is taken to configure a
  `basetemp` directory for the sub processes automatically. `--basetemp` is
  cleared before each test run.
- **Implication for GLOBIN:** a hand-rolled runner gets none of that help, so it
  must pass `--basetemp` itself if shards are ever run concurrently. This design
  runs them **sequentially**, so the collision cannot arise today; the fact is
  recorded because it is the first thing that would break if a concurrent mode
  were ever added, and [ADR-0036](../adr/0036-test-execution-is-sharded-by-a-stable-digest-not-by-a-plugin.md)
  declines to add one.

### S-16 — coverage.py: data files, and what `combine` needs

- **Canonical location:** https://coverage.readthedocs.io/en/latest/config.html
- **Accessed:** 2026-08-14
- **Authority:** Primary — the project documenting its own configuration.
- **Supports:** `[run] data_file` names the file, and the `COVERAGE_FILE`
  environment variable overrides it. `[run] parallel` appends machine name,
  process id and a random suffix so that many processes can be collected.
  `combine` merges such files, deleting the inputs unless `--keep` is passed.
  `relative_files` and a `[paths]` section are what allow combining across
  machines or directories.
- **Implication for GLOBIN:** each shard child is given its own `COVERAGE_FILE`,
  which is **mandatory rather than tidy** — the plugin erases the data file at
  start unless appending, so two children sharing one would erase each other's
  work, and both would overwrite the `.coverage` the last `full` gate left at the
  repository root. `parallel`, `relative_files` and `[paths]` are deliberately
  **not** added: all three are read by the existing `coverage` and `full` gates,
  and ADR-0032 condition 5 forbids a tooling addition that changes what an
  existing gate does. The stated cost is that combining is same-machine only.

### S-17 — pytest-cov: the coverage threshold a child inherits

- **Canonical location:** https://pytest-cov.readthedocs.io/en/latest/config.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** `--cov-fail-under` sets the minimum coverage percentage, and when
  it is not given the plugin falls back to the `fail_under` value in the coverage
  configuration. **Verified by running it on this machine:** one quarter of this
  suite, run as a shard with `--cov` and no override, passed all 240 of its tests
  and still exited `1`, reporting that the required coverage of 95.0% was not
  reached and total coverage was 87.43%.
- **Implication for GLOBIN:** every shard child passes `--cov-fail-under=0`.
  Without it the repository's whole-suite floor is applied to a fraction of the
  suite, so **every shard exits 1** and the gate reports a broken suite while
  nothing is broken — a false red indistinguishable from a real one.

### S-18 — CPython: `PYTHONHASHSEED` is read at interpreter startup

- **Canonical location:** https://docs.python.org/3/using/cmdline.html
- **Accessed:** 2026-08-14
- **Authority:** Primary.
- **Supports:** the variable seeds the hashing of `str` and `bytes`. The integer
  must be a decimal number in the range 0 to 4294967295, and the value 0 disables
  hash randomisation. It is processed during interpreter startup, before the
  runtime is initialised.
- **Implication for GLOBIN:** the seed is part of the **child environment** and
  cannot be a fixture — assigning it inside a running process changes nothing
  about that process. It also bounds what the seed option accepts, and it is why
  the test proving the shard mapping is hash-seed-independent has to start two
  real interpreters rather than manipulating anything in-process.

### S-19 — pytest-xdist and execnet: evaluated and not adopted

- **Canonical location:** https://pypi.org/project/pytest-xdist/
- **Accessed:** 2026-08-14
- **Authority:** Primary — the projects publishing their own metadata.
- **Supports:** the latest `pytest-xdist` is 3.8.0, released 2025-07-01, with
  `requires_python >=3.9` and classifiers listing Python 3.9 through 3.13. Its
  dependencies are `execnet>=2.1` and `pytest>=7.0.0`. The latest `execnet` is
  2.1.2, released 2025-11-12, with classifiers listing Python 3.8 through 3.12.
  The xdist changelog records Python 3.13 support arriving in 3.7.0 and mentions
  neither Python 3.14 nor pytest 9.
- **Implication for GLOBIN:** **not adopted, and this entry is the evidence for
  the refusal rather than a plan to revisit soon.** The primary reason is
  governance: ADR-0032 condition 3 forbids a new dependency and routes one to
  Phase 014, which does not exist yet. The secondary reason is that this
  repository runs Python 3.14.5 and pytest 9.0.3, and neither package declares
  support for either. Recorded so that the Phase 014 review starts from what has
  already been checked.

---

## Facts this phase could not establish

### S-11 — The behaviour of a coarse system clock, not reproduced

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-14
- **Authority:** Primary for the interface; **not established** for the
  behaviour claimed below.
- **Supports:** `time.get_clock_info` reports an implementation and a resolution
  per clock, and those differ by platform and by CPython build. On this machine
  both clocks report `1e-07`. It is understood that a Windows host whose wall
  clock falls back to `GetSystemTimeAsFileTime()` has a granularity closer to
  15.6 ms, which would make two consecutive readings identical.
- **Implication for GLOBIN:** **not reproduced.** No machine exhibiting the
  coarse behaviour was available in this phase, so the claim is treated as
  plausible rather than verified. The response is defensive regardless and costs
  nothing: no test in this repository asserts that two real clock readings
  differ, only that the later is not smaller. If the coarse case never
  materialises the tests are still correct; if it does, they do not flake. The
  phase that pins interpreter and platform behaviour is **018**.
