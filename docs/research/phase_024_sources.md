# Phase 024 — Source Ledger

The workload benefit harness, and the runtime health and support-bundle layer
delivered alongside it. What `psutil` documents about the counters this phase
reads; what CPython guarantees about the allocator tracer, the thread inventory,
the archive format and the clocks; and what this host actually answers when asked.

Every claim Phase 024 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

**Three entries below record a trap rather than a specification, and each one
would have produced a plausible wrong answer.** A first `cpu_percent` call returns
a meaningless zero; a CUDA timing that does not synchronise measures submission
rather than work; and a ZIP member stamped with a real modification time makes an
archive differ from itself. None of the three fails loudly. All three fail in the
flattering direction, which is why they are recorded rather than remembered.

---

## The process and host counters

### S-01 — `psutil.Process.oneshot()` is a caching context for several fields at once

- **Canonical location:** https://psutil.readthedocs.io/en/latest/#psutil.Process.oneshot
- **Accessed:** 2026-08-16
- **Authority:** Primary — the library's own reference documentation.
- **Supports:** `oneshot()` is documented as a context manager that caches process
  information, so that several fields are satisfied from a smaller number of reads
  of the operating system's process table.

- **Implication for GLOBIN:** `globin.adapters.health.PsutilProcessProbe.summary`
  reads resident set, virtual size, CPU times, thread count and handle count inside
  one `oneshot()` block. The performance is a side benefit; the reason it is
  required is correctness. Read field by field, a resident set from one instant
  would sit beside a thread count from another, and the result would describe no
  single moment.

### S-02 — the first `cpu_percent` call on a process returns a meaningless `0.0`

- **Canonical location:** https://psutil.readthedocs.io/en/latest/#psutil.Process.cpu_percent
- **Accessed:** 2026-08-16
- **Authority:** Primary — the library documents the behaviour explicitly and
  advises ignoring the first result.
- **Supports:** The value is a ratio computed over the interval since the previous
  call. The first call has no previous reading to form an interval with, so it
  reports `0.0` regardless of what the process is doing.

- **Implication for GLOBIN:** `globin diagnostics snapshot` measures once and
  exits, so there is no interval and therefore no honest percentage. The snapshot
  reports cumulative `cpu_times` — a fact rather than a rate — and records
  `cpu_percent` as `Availability.UNAVAILABLE` with the reason
  `HEALTH_CPU_NOT_SAMPLED`. Reporting `0.0` would have said the process is idle,
  which is a conclusion nobody drew.

### S-03 — `num_handles` is a Windows-only counter and raises elsewhere

- **Canonical location:** https://psutil.readthedocs.io/en/latest/#psutil.Process.num_handles
- **Accessed:** 2026-08-16
- **Authority:** Primary — the reference marks the method Windows-only.
- **Supports:** The attribute exists on Windows. On platforms without it the
  attribute is absent rather than returning a neutral value.

- **Implication for GLOBIN:** the probe looks the attribute up rather than calling
  it blindly, and its absence becomes `Availability.UNSUPPORTED` with
  `HEALTH_COUNTER_UNSUPPORTED`. Reporting `0` would invent a measurement, which is
  the failure `RUNTIME_HEALTH.md` is shaped to prevent.

### S-04 — `memory_full_info` is documented as slower and may need higher privilege

- **Canonical location:** https://psutil.readthedocs.io/en/latest/#psutil.Process.memory_full_info
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** The reference states that it is more expensive than `memory_info`
  and that on some platforms it may raise `AccessDenied` for processes the caller
  does not own.

- **Implication for GLOBIN:** it is not on the normal snapshot path. `memory_info`
  supplies resident set and virtual size, which are the two figures the health
  checks compare against thresholds.

### S-05 — this host's own answers, measured rather than assumed

- **Canonical location:** measured on the target host through
  `globin.adapters.health`, psutil 7.2.2, CPython 3.14.5, Windows 11. The API asked
  is https://psutil.readthedocs.io/en/latest/#psutil.Process.memory_info and its
  neighbours; what is recorded below is this machine's answer, not the
  documentation's.
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** resident set 26,030,080 bytes; 4 OS threads; **179 handles**, so
  the Windows-only counter is genuinely present here; 16 logical processors;
  4,550,684,672 bytes of available memory; one filesystem behind the runtime tree
  with 77,623,185,408 bytes free.

- **Implication for GLOBIN:** the handle count is exercised on a host that has it,
  rather than only through a substituted probe, so the `UNSUPPORTED` branch is a
  deliberate fallback rather than the only path anybody has run.

### S-06 — psutil declares no runtime dependencies and ships no `py.typed`

- **Canonical location:** https://pypi.org/pypi/psutil/json, and the installed
  distribution in this repository's `.venv`.
- **Accessed:** 2026-08-16
- **Authority:** Primary — the index's own metadata, and the installed package.
- **Supports:** every entry in `requires_dist` is guarded by `extra == "dev"` or
  `extra == "test"`, so the installed set is one distribution. The installed
  package directory contains no `py.typed` marker. The published wheel
  `psutil-7.2.2-cp37-abi3-win_amd64.whl` is a limited-API build, and its licence is
  `BSD-3-Clause`.

- **Implication for GLOBIN:** question 1 of
  [`../DEPENDENCY_POLICY.md`](../DEPENDENCY_POLICY.md) is answered with a measured
  zero, the `abi3` tag is what lets `allow_source = false` hold for the pinned
  CPython 3.14, and the absent `py.typed` is the reason `pyproject.toml` carries a
  mypy override rather than relying on the library's own annotations.

---

## The CPython diagnostic surface

### S-07 — `tracemalloc` is documented as costing CPU and memory while it runs

- **Canonical location:** https://docs.python.org/3/library/tracemalloc.html
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** the module traces memory blocks allocated by Python; `start()`
  takes a frame count that decides how many frames each traceback stores;
  `get_traced_memory()` returns current and peak size; `get_tracemalloc_memory()`
  returns the memory used by the module itself; and the default frame count is 1.

- **Implication for GLOBIN:** tracing is off by default and is enabled only by a
  typed setting or the explicit `diagnostics memory` verb. The frame depth is a
  bounded setting because the cost is paid per allocation rather than once, and the
  module's own overhead is reported so a reader can see what the diagnostic cost.

### S-08 — `time.monotonic_ns` and `time.perf_counter_ns` cannot go backwards

- **Canonical location:** https://docs.python.org/3/library/time.html
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** `monotonic()` is documented as a clock that cannot go backwards and
  is not affected by system clock updates, with its reference point undefined so
  that only differences are valid. `perf_counter()` is the highest-resolution clock
  available. The `_ns` variants return integer nanoseconds to avoid the precision
  loss of a float.

- **Implication for GLOBIN:** uptime and every check duration are differences of
  monotonic readings, so a manual clock correction or an NTP slew cannot produce a
  negative uptime. The benchmark harness times with `perf_counter_ns`. The wall
  clock appears only as `generated_at`, which is what a human reads.

### S-09 — `threading.enumerate` lists live threads and excludes terminated ones

- **Canonical location:** https://docs.python.org/3/library/threading.html
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** `enumerate()` returns currently alive `Thread` objects, excluding
  terminated threads and threads not yet started. A `Thread` exposes `name`,
  `ident`, `native_id`, `is_alive()` and `daemon`.

- **Implication for GLOBIN:** the thread inventory filters nothing itself. Names
  are sanitised and bounded before publication because a thread name is set by
  whoever created the thread and a dependency may put anything in one. No stack is
  taken: Phase 023's `faulthandler` already owns native tracebacks.

### S-10 — a ZIP member cannot carry a date before 1980

- **Canonical location:** https://docs.python.org/3/library/zipfile.html
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** `ZipInfo.date_time` is a six-tuple and the documentation states
  that the ZIP file format does not support timestamps before 1980.
  `ZipFile.writestr` accepts a `ZipInfo` instance, so a caller may set the member's
  metadata rather than letting the library derive it.

- **Implication for GLOBIN:** every bundle member is stamped
  `(1980, 1, 1, 0, 0, 0)` — the earliest legal value rather than an arbitrary one —
  with fixed external attributes and a named compression method and level. Real
  modification times are the largest source of nondeterminism in an archive, and on
  this host they would additionally record when an operator was at their machine.

### S-11 — `os.replace` is atomic only within one filesystem

- **Canonical location:** https://docs.python.org/3/library/os.html#os.replace
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** the rename is documented as atomic when both paths are on the same
  filesystem, and the operation may fail across filesystems on some platforms.

- **Implication for GLOBIN:** a bundle is built under a `.partial` name **in the
  destination's own directory** rather than in the system temporary directory,
  then validated, hashed and moved. This is Phase 022's publication sequence
  applied to bytes rather than to a JSON document.

### S-12 — `os.process_cpu_count` reports the processors this process may use

- **Canonical location:** https://docs.python.org/3/library/os.html#os.process_cpu_count
- **Accessed:** 2026-08-16
- **Authority:** Primary.
- **Supports:** added in Python 3.13, it returns the number of logical CPUs usable
  by the calling process, honouring an affinity mask where one is in force.
  `os.cpu_count()` reports the machine's total instead.

- **Implication for GLOBIN:** the host probe prefers `process_cpu_count` and falls
  back to `cpu_count`, because a resource question is about what this process may
  use rather than about what the machine has.

---

## The device backend

### S-13 — CUDA work is queued asynchronously and must be synchronised before timing

- **Canonical location:** https://pytorch.org/docs/stable/notes/cuda.html
- **Accessed:** 2026-08-16
- **Authority:** Primary — the library's own note on CUDA semantics.
- **Supports:** GPU operations are documented as asynchronous: they are queued to a
  device stream and control returns to Python before the work completes.
  `torch.cuda.synchronize()` waits for the queued work to finish, and the note
  states explicitly that benchmarks must account for this.

- **Implication for GLOBIN:** `tools/quality/benchmark/probes.py` calls
  `torch.cuda.synchronize()` inside every timed callable. Without it a timed block
  would measure submission rather than execution and report a speedup of several
  hundred — the single most common way a GPU benchmark lies, and it lies in the
  flattering direction. **This code has not been executed on this host**: `torch`
  is Phase 183's to adopt and is in no lock here, so every CUDA workload currently
  records `UNAVAILABLE`. The claim above is taken from the specification and is
  marked as unverified by measurement, per
  [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).
