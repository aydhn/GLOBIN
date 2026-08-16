# Phase 023 — Source Ledger

NVIDIA driver and CUDA capability detection, and the runtime diagnostics delivered
alongside it. What `nvidia-smi` documents about its own query vocabulary; what this
host actually answers when asked; and what CPython guarantees about the four hooks
through which a fault reaches a diagnostic layer.

Every claim Phase 023 makes about an external system is recorded here, per
[`../SOURCE_POLICY.md`](../SOURCE_POLICY.md).

**Two kinds of entry appear below, and the difference is stated in each
`Authority` line.** Some record what a primary document *specifies*. Most of the
GPU entries record what was *measured on the target host* — and for this phase
that is not a supplement, it is the substance. The roadmap asked for detection
"without assuming any of them", and four of the six GPU entries below exist
because a plausible assumption turned out to be **false on this machine**. A
specification could not have established that; only asking could.

`nvidia-smi` is a primary source in a slightly unusual sense worth naming: it
documents its own accepted vocabulary through `--help-query-gpu`, so the tool and
the specification are the same artefact. That is stronger than a web page, not
weaker — the answer came from the exact build installed here.

---

## The NVIDIA query interface

### S-01 — `nvidia-smi --help-query-gpu` documents the four fields this phase reads

- **Canonical location:** https://docs.nvidia.com/deploy/nvidia-smi/index.html; read on this host as `nvidia-smi --help-query-gpu`, NVIDIA-SMI 610.88
- **Accessed:** 2026-08-16
- **Authority:** Primary, and measured on the target host. The tool ships with the
  display driver and states its own accepted field names.
- **Supports:** The output lists, among others, `"driver_version"`,
  `"name" or "gpu_name"`, `"memory.total"` and `"compute_cap"`.

- **Implication for GLOBIN:** These four are the whole of `query_fields` in
  [`../engineering/gpu-contract.toml`](../engineering/gpu-contract.toml). A field
  outside this list is a field somebody guessed, so the contract enumerates them
  and the gate asks for nothing else.

### S-02 — `cuda_version` is **not** a queryable field

- **Canonical location:** https://docs.nvidia.com/deploy/nvidia-smi/index.html; measured as `nvidia-smi --query-gpu=driver_version,cuda_version --format=csv,noheader`
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** The command answered `Field "cuda_version" is not a valid field to
  query.` and produced no rows.

- **Implication for GLOBIN:** This is the trap that justifies the whole
  `[[forbidden_field]]` table. Adding `cuda_version` to the query does not merely
  omit a column — it breaks the **entire** query, so a detector that assumed the
  field existed would lose the driver version and the compute capability too. The
  CUDA runtime version therefore has to come from a different interface, which is
  S-04.

### S-03 — `DRIVER version` in `--version` is self-declared deprecated

- **Canonical location:** https://docs.nvidia.com/deploy/nvidia-smi/index.html; measured as `nvidia-smi --version`, NVIDIA-SMI 610.88
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** The output line reads
  `DRIVER version      : Deprecated, see "KMD version" instead`.

- **Implication for GLOBIN:** A reader taking the first label containing *DRIVER*
  would record the string `Deprecated, see "KMD version" instead` as a driver
  version, and nothing downstream could distinguish it from a measurement. Two
  defences follow: the label is named in `[[forbidden_field]]`, and every recorded
  version is shape-checked against `^\d+(\.\d+)*$` so prose is refused even if a
  future label slips past the list.

### S-04 — `CUDA version` is deprecated in favour of `CUDA UMD version`, which reports `13.3`

- **Canonical location:** https://docs.nvidia.com/deploy/nvidia-smi/index.html; measured as `nvidia-smi --version`, NVIDIA-SMI 610.88
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** The output carries both
  `CUDA version        : Deprecated, see "CUDA UMD version" instead` and
  `CUDA UMD version    : 13.3`. The banner from bare `nvidia-smi` agrees, reading
  `CUDA UMD Version: 13.3` — note that this is **not** the older `CUDA Version:`
  spelling that a screen-scraper would look for.

- **Implication for GLOBIN:** The driver-side CUDA runtime is read from the
  `--version` table, skipping any label the contract forbids and any value that
  says *Deprecated*, and taking the first remaining CUDA label whose value has the
  shape of a version. The banner is not parsed at all: its format has already
  changed once, and a human-readable header is exactly what
  [`../SOURCE_POLICY.md`](../SOURCE_POLICY.md) means by a page rather than an
  interface.

### S-05 — this host reports one device, compute capability 8.6, driver 610.88

- **Canonical location:** https://docs.nvidia.com/deploy/nvidia-smi/index.html; measured as `nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv,noheader`
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** `NVIDIA GeForce RTX 3050 Laptop GPU, 610.88, 8.6, 4096 MiB`.

- **Implication for GLOBIN:** The values are recorded in
  `.globin/gpu/gpu-manifest.json` and **not** in the contract, for the reason
  [`../engineering/GPU_CAPABILITY.md`](../engineering/GPU_CAPABILITY.md) gives: a
  driver updates on its own schedule, and a pinned version would go red on a day
  nobody chose. This entry is the evidence that the gate reports something true on
  the host it was written on, not a baseline anything compares against.

### S-06 — a CUDA runtime is present while no CUDA toolkit is installed

- **Canonical location:** https://docs.nvidia.com/deploy/nvidia-smi/index.html; measured on this host as `where nvcc`, and by reading `CUDA_PATH`
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** `nvcc` is not on `PATH` and `CUDA_PATH` is unset, while S-04 shows
  a CUDA user-mode runtime at 13.3.

- **Implication for GLOBIN:** The two are asked separately and neither is derived
  from the other. This host is the proof that the inference would be wrong in at
  least one direction. The distinction is *a prebuilt CUDA wheel would run here*
  versus *CUDA source could be built here*, and Phase 024 needs both halves when
  it asks which workloads benefit. `cuda.toolkit_present` is recorded `ABSENT` and
  owned by Phase 025, which is the phase the roadmap gives native provisioning to.

---

## The CPython diagnostic surface

### S-07 — `faulthandler.register` does not exist on Windows

- **Canonical location:** https://docs.python.org/3/library/faulthandler.html; measured as `hasattr(faulthandler, "register")` on CPython 3.14.5, Windows
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host, against the pinned interpreter.
- **Supports:** The attribute is absent. `faulthandler.enable` is present.

- **Implication for GLOBIN:** The brief's mention of signal registration is not
  implementable here and is not attempted. `faulthandler.enable(file=..., all_threads=True)`
  covers what matters on this platform — a segmentation fault or an abort raised
  by native code inside a wheel — without assuming a signal set Windows does not
  have. Recording the absence rather than guarding it with a `hasattr` that nobody
  documented is the same discipline `PlatformShutdownSignals` applies to
  `SIGBREAK`.

### S-08 — `threading.ExceptHookArgs` is a structseq carrying exactly four attributes

- **Canonical location:** https://docs.python.org/3/library/threading.html; measured as `threading.ExceptHookArgs` on CPython 3.14.5
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** The constructed object exposes `exc_type`, `exc_value`,
  `exc_traceback` and `thread`. Its concrete type is `_thread._ExceptHookArgs`
  with `n_fields == 4`; it is **not** a `collections.namedtuple` and has no
  `_fields`.

- **Implication for GLOBIN:** The thread hook reads those four names by attribute
  and nothing else. A test double therefore needs only to expose them, which is
  what lets the hook be exercised without starting a thread. The thread's *name*
  is copied out and the objects themselves are not retained: holding a reference
  to a dead thread's exception in a long-lived attribute keeps every frame of its
  traceback alive for the rest of the run.

### S-09 — `logging.captureWarnings` redirects warnings into the logging package

- **Canonical location:** https://docs.python.org/3/library/logging.html; read as `logging.captureWarnings.__doc__` on CPython 3.14.5
- **Accessed:** 2026-08-16
- **Authority:** Primary. CPython's own documentation of the function it ships.
- **Supports:** "If capture is true, redirect all warnings to the logging package."

- **Implication for GLOBIN:** Warning capture needs no separate mechanism. Warnings
  arrive at the `py.warnings` logger, the bridge handler is attached to the root
  logger, and one installation therefore covers both third-party records and
  Python's own warnings — one thing to install and one thing to remove. The
  warning **filters** are untouched: which warnings are produced is a different
  question from where they go, and the suite's `filterwarnings = ["error"]` is
  deliberate.

### S-10 — the standard library's level numbers are GLOBIN's severity values

- **Canonical location:** https://docs.python.org/3/library/logging.html; measured as `logging.DEBUG`, `.INFO`, `.WARNING`, `.ERROR`, `.CRITICAL`
- **Accessed:** 2026-08-16
- **Authority:** Measured on the target host.
- **Supports:** They are `10`, `20`, `30`, `40`, `50`, which are exactly the values
  of `globin.domain.observability.Severity`.

- **Implication for GLOBIN:** The bridge needs no mapping table, which is what
  `Severity`'s own docstring predicted when it called the borrowing deliberate:
  "a mapping table between two enumerations is a thing that drifts". The bridge
  still rounds *down* to the nearest defined severity rather than calling
  `Severity(levelno)`, because libraries invent intermediate levels — `15`, `25` —
  and an exact lookup would raise `ValueError` inside the logging system rather
  than record the message.

### S-11 — `logging.Handler.handleError` is the documented channel for a failing handler

- **Canonical location:** https://docs.python.org/3/library/logging.html; confirmed as `logging.Handler.handleError` on CPython 3.14.5
- **Accessed:** 2026-08-16
- **Authority:** Primary. CPython's own documented method.
- **Supports:** The method exists on `logging.Handler`.

- **Implication for GLOBIN:** The bridge reports its own failures through it rather
  than raising. Raising would push an exception back into whichever library was
  merely trying to log something, turning a diagnostic problem into that library's
  problem. This is the one place GLOBIN catches broadly on purpose, and
  [`../engineering/ENGINEERING_CONTRACT.md`](../engineering/ENGINEERING_CONTRACT.md)
  invariant 23 is satisfied because the failure is reported rather than discarded.
